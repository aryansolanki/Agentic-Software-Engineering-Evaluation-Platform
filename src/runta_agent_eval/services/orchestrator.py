from __future__ import annotations

import asyncio
import json
import logging
import shutil
import shlex
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from runta_agent_eval.core.config import Settings
from runta_agent_eval.core.db import Database, json_text
from runta_agent_eval.core.models import EvaluationMode, SourceMode, TaskCreate
from runta_agent_eval.runta.gateway import RuntaGateway, RuntimeHandle
from runta_agent_eval.services.diffing import build_workspace_diff
from runta_agent_eval.services.snapshot import REMOTE_SNAPSHOT_SCRIPT, extract_snapshot_zip
from runta_agent_eval.services.evaluation import (
    CandidateEvidence,
    apply_ai_ranking,
    deterministic_score,
    finalize_ranking,
    run_ai_judge,
    select_winner,
)

logger = logging.getLogger(__name__)

CANDIDATE_STRATEGIES = (
    "Minimal root-cause strategy: identify the exact failing behavior, make the smallest safe code change, and verify it.",
    "Test-driven strategy: start from failing tests/specification, derive the required behavior, then make the narrowest patch.",
    "Specification-first strategy: independently derive intended behavior from the task and public interfaces before editing implementation details.",
    "Regression-hunter strategy: inspect nearby invariants and likely hidden edge cases, then preserve existing behavior while fixing the defect.",
    "Simplification strategy: prefer the clearest minimal implementation and remove accidental complexity only when needed for correctness.",
    "Skeptical-review strategy: challenge the obvious fix, verify the root cause with evidence, and avoid patching symptoms.",
    "Data-flow strategy: trace inputs through transformations and outputs, then correct the earliest incorrect state transition or calculation.",
    "Interface-contract strategy: focus on API/function contracts, callers, return values, and compatibility before choosing the patch.",
    "Edge-case strategy: emphasize boundary values, error paths, and type/value corner cases while keeping the production change small.",
    "Maintainability strategy: choose the correct solution that a future engineer can understand quickly, with minimal surprise and duplication.",
    "Alternative-design strategy: look for a meaningfully different but still small implementation path and verify it against the full suite.",
    "Reviewer strategy: behave like a cautious code reviewer—inspect the likely patch surface, regression risks, and tests before committing the final change.",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def strategy_for_candidate(ordinal: int) -> str:
    if ordinal < 1:
        raise ValueError("candidate ordinal must be >= 1")
    return CANDIDATE_STRATEGIES[(ordinal - 1) % len(CANDIDATE_STRATEGIES)]


def extract_agent_status(agent_output: str) -> str:
    """Recover the worker's terminal JSON status from stdout/stderr text."""
    for line in reversed(agent_output.splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        status = payload.get("status") if isinstance(payload, dict) else None
        if isinstance(status, str) and status:
            return status
    return "unknown"


def _exit_code(result: object) -> int:
    return int(getattr(result, "exit_code", 1))


def _result_text(result: object) -> str:
    return ((getattr(result, "stdout_text", "") or "") + "\n" + (getattr(result, "stderr_text", "") or "")).strip()


def _require_success(result: object, label: str) -> None:
    code = _exit_code(result)
    if code != 0:
        details = _result_text(result)
        raise RuntimeError(f"{label} failed with exit code {code}: {details[-4000:]}")


class Orchestrator:
    def __init__(self, settings: Settings, db: Database):
        self.settings = settings
        self.db = db
        self.tasks: dict[str, asyncio.Task[None]] = {}

    async def submit(self, request: TaskCreate) -> str:
        try:
            if request.candidate_count > self.settings.max_candidates:
                raise ValueError(f"candidate_count exceeds MAX_CANDIDATES={self.settings.max_candidates}")
            run_id = uuid.uuid4().hex
            now = utc_now()
            await self.db.execute(
                "INSERT INTO runs(id,created_at,updated_at,status,name,task,candidate_count,evaluation_mode,request_json) VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    run_id,
                    now,
                    now,
                    "queued",
                    request.name,
                    request.task,
                    request.candidate_count,
                    request.evaluation_mode.value,
                    request.model_dump_json(),
                ),
            )
            self.tasks[run_id] = asyncio.create_task(self._run(run_id, request), name=f"run-{run_id}")
            return run_id
        except Exception:
            logger.exception("Failed submitting task")
            raise

    async def _run(self, run_id: str, request: TaskCreate) -> None:
        baseline: RuntimeHandle | None = None
        candidate_handles: list[RuntimeHandle] = []
        try:
            await self._set_run_status(run_id, "preparing")
            run_dir = self.settings.artifact_dir / run_id
            run_dir.mkdir(parents=True, exist_ok=True)
            async with RuntaGateway(self.settings) as gateway:
                await gateway.ensure_openai_secret()
                hosts = await self._allowed_hosts(request)
                baseline = await gateway.create_runtime(
                    f"rae-{run_id[:8]}-base",
                    allowed_hosts=hosts,
                )
                await self._prepare_baseline(gateway, baseline, request)
                baseline_snapshot = run_dir / "_baseline_workspace"
                await self._download_workspace_snapshot(gateway, baseline, baseline_snapshot)
                checkpoint = await gateway.checkpoint(baseline, f"rae-{run_id[:8]}-ready")
                await self._set_run_status(run_id, "forking")

                candidate_handles = await asyncio.gather(
                    *[
                        self._create_candidate(gateway, run_id, index, checkpoint.id, hosts)
                        for index in range(1, request.candidate_count + 1)
                    ]
                )

                await self._set_run_status(run_id, "agents_running")
                evidence = await asyncio.gather(
                    *[
                        self._run_candidate(gateway, run_id, request, handle, index, run_dir, baseline_snapshot)
                        for index, handle in enumerate(candidate_handles, start=1)
                    ]
                )

                for item in evidence:
                    item.deterministic_score = await deterministic_score(item)

                judge_result = None
                if request.evaluation_mode in {EvaluationMode.AI_JUDGE, EvaluationMode.HYBRID}:
                    await self._set_run_status(run_id, "ai_judging")
                    judge_result = await run_ai_judge(
                        self.settings,
                        gateway,
                        run_id,
                        request.task,
                        evidence,
                        keep_runtime=request.keep_runtimes,
                        model=request.model or self.settings.openai_model,
                    )
                    await apply_ai_ranking(evidence, judge_result)

                await finalize_ranking(evidence, request.evaluation_mode.value)
                winner = select_winner(evidence)
                await self._persist_scores(run_id, evidence)
                outcome = "winner_selected" if winner is not None else "no_acceptable_candidate"
                await self.db.execute(
                    "UPDATE runs SET status=?, updated_at=?, winner_candidate_id=?, summary_json=? WHERE id=?",
                    (
                        "completed",
                        utc_now(),
                        winner.candidate_id if winner else None,
                        json_text(
                            {
                                "outcome": outcome,
                                "winner": winner.candidate_id if winner else None,
                                "passing_candidates": [c.candidate_id for c in evidence if c.eligible],
                                "evaluation_mode": request.evaluation_mode.value,
                                "judge": judge_result,
                            }
                        ),
                        run_id,
                    ),
                )

                if not request.keep_runtimes:
                    await asyncio.gather(*(self._safe_delete(gateway, h) for h in candidate_handles))
                    if baseline is not None:
                        await self._safe_delete(gateway, baseline)
        except Exception as exc:
            logger.exception("Run %s failed", run_id)
            await self.db.execute(
                "UPDATE runs SET status=?, updated_at=?, error=? WHERE id=?",
                ("failed", utc_now(), str(exc), run_id),
            )
        finally:
            self.tasks.pop(run_id, None)


    async def _download_workspace_snapshot(
        self,
        gateway: RuntaGateway,
        handle: RuntimeHandle,
        destination: Path,
    ) -> None:
        """Download a source-only workspace snapshot without runtime dependency symlinks."""
        script_path = "/workspace/rae_snapshot.py"
        archive_path = "/workspace/rae_workspace_snapshot.zip"
        local_archive = destination.parent / f".{destination.name}.snapshot.zip"
        await gateway.write(handle, script_path, REMOTE_SNAPSHOT_SCRIPT)
        result = await gateway.exec(
            handle,
            f"python3 {script_path} /workspace/repo {archive_path}",
            timeout=300,
            cwd="/workspace",
        )
        _require_success(result, "Workspace snapshot creation")
        try:
            if local_archive.exists():
                local_archive.unlink()
            await gateway.download(handle, archive_path, local_archive)
            await asyncio.to_thread(extract_snapshot_zip, local_archive, destination)
        finally:
            if local_archive.exists():
                local_archive.unlink()
            try:
                await gateway.exec(
                    handle,
                    f"rm -f {script_path} {archive_path}",
                    timeout=30,
                    cwd="/workspace",
                )
            except Exception:
                logger.warning("Could not remove temporary snapshot files from %s", handle.name)

    async def _allowed_hosts(self, request: TaskCreate) -> list[str]:
        try:
            hosts = ["api.openai.com", *request.allowed_hosts]
            if request.source_mode == SourceMode.GIT and request.git_url:
                parsed = urlparse(str(request.git_url))
                if parsed.hostname:
                    hosts.append(parsed.hostname)
            return list(dict.fromkeys(hosts))
        except Exception:
            logger.exception("Could not compute allowed hosts")
            raise

    async def _prepare_baseline(self, gateway: RuntaGateway, baseline: RuntimeHandle, request: TaskCreate) -> None:
        try:
            if request.source_mode == SourceMode.FIXTURE:
                fixture = Path(__file__).resolve().parents[3] / "fixtures" / "buggy_calc"
                await gateway.upload(baseline, fixture, "/workspace/repo")
            else:
                clone = await gateway.exec(
                    baseline,
                    f"git clone --depth 1 {shlex.quote(str(request.git_url))} /workspace/repo",
                    timeout=300,
                )
                _require_success(clone, "Git clone")

            if request.setup_command.strip():
                setup = await gateway.exec(
                    baseline, request.setup_command, timeout=600, cwd="/workspace/repo"
                )
                _require_success(setup, "Repository setup command")

            # Do not manufacture a Git repository for uploaded fixtures.
            # Artifact diffs are generated from immutable baseline/candidate directory
            # snapshots, so Git metadata is not required for correctness. Public Git
            # sources already arrive as real clones and retain their native repository.

            baseline_test = await gateway.exec(
                baseline, request.test_command, timeout=300, cwd="/workspace/repo"
            )
            await self.db.add_observation(
                utc_now(),
                "baseline",
                "Baseline test executed before checkpoint",
                f"exit_code={getattr(baseline_test, 'exit_code', None)}; a failing baseline can be expected for bug-fix tasks.",
            )
        except Exception:
            logger.exception("Baseline preparation failed")
            raise

    async def _create_candidate(
        self,
        gateway: RuntaGateway,
        run_id: str,
        ordinal: int,
        checkpoint_id: str,
        hosts: list[str],
    ) -> RuntimeHandle:
        try:
            handle = await gateway.create_runtime(
                f"rae-{run_id[:8]}-c{ordinal:02d}",
                checkpoint_id=checkpoint_id,
                allowed_hosts=hosts,
                with_openai_secret=True,
            )
            worker = Path(__file__).resolve().parents[1] / "workers" / "agent_worker.py"
            await gateway.upload(handle, worker, "/workspace/agent_worker.py")
            candidate_id = f"{run_id}-c{ordinal:02d}"
            await self.db.execute(
                "INSERT INTO candidates(id,run_id,ordinal,runtime_id,runtime_name,status) VALUES(?,?,?,?,?,?)",
                (candidate_id, run_id, ordinal, handle.id, handle.name, "ready"),
            )
            return handle
        except Exception:
            logger.exception("Candidate %s creation failed", ordinal)
            raise

    async def _run_candidate(
        self,
        gateway: RuntaGateway,
        run_id: str,
        request: TaskCreate,
        handle: RuntimeHandle,
        ordinal: int,
        run_dir: Path,
        baseline_snapshot: Path,
    ) -> CandidateEvidence:
        candidate_id = f"{run_id}-c{ordinal:02d}"
        strategy = strategy_for_candidate(ordinal)
        try:
            await self.db.execute("UPDATE candidates SET status=? WHERE id=?", ("agent_running", candidate_id))
            task_path = "/workspace/task.txt"
            await gateway.write(handle, task_path, request.task)
            env = {
                "RAE_TASK_FILE": task_path,
                "RAE_REPO": "/workspace/repo",
                "RAE_MODEL": request.model or self.settings.openai_model,
                "RAE_API_URL": self.settings.openai_api_url,
                "RAE_MAX_STEPS": str(self.settings.agent_max_steps),
                "RAE_TEST_COMMAND": request.test_command,
                "RAE_STRATEGY": strategy,
            }
            agent = await gateway.exec(
                handle,
                "python3 /workspace/agent_worker.py",
                timeout=1200,
                cwd="/workspace/repo",
                env=env,
            )
            test = await gateway.exec(handle, request.test_command, timeout=300, cwd="/workspace/repo")

            artifact_dir = run_dir / f"candidate-{ordinal:02d}"
            if artifact_dir.exists():
                await asyncio.to_thread(shutil.rmtree, artifact_dir)
            artifact_dir.mkdir(parents=True, exist_ok=True)
            candidate_workspace = artifact_dir / "workspace"
            await self._download_workspace_snapshot(gateway, handle, candidate_workspace)

            # Build the exported patch from immutable baseline/candidate snapshots.
            # This is intentionally independent of `.git` preservation and also
            # catches edits even if an agent commits inside the runtime.
            diff_text = await asyncio.to_thread(
                build_workspace_diff, baseline_snapshot, candidate_workspace
            )

            agent_exit_code = int(getattr(agent, "exit_code", 1))
            test_exit_code = int(getattr(test, "exit_code", 1))
            test_output = (getattr(test, "stdout_text", "") or "") + "\n" + (getattr(test, "stderr_text", "") or "")
            agent_output = (getattr(agent, "stdout_text", "") or "") + "\n" + (getattr(agent, "stderr_text", "") or "")
            agent_status = extract_agent_status(agent_output)

            if test_exit_code == 0 and agent_exit_code == 0:
                candidate_status = "passed"
                candidate_error = None
            elif test_exit_code == 0:
                candidate_status = "passed_with_agent_warning"
                candidate_error = f"agent_exit_code={agent_exit_code}; agent_status={agent_status}"
            elif agent_exit_code == 2 or agent_status == "max_steps":
                candidate_status = "max_steps"
                candidate_error = "Agent reached max steps before producing a passing solution."
            elif agent_exit_code != 0:
                candidate_status = "agent_error"
                candidate_error = f"agent_exit_code={agent_exit_code}; agent_status={agent_status}"
            elif not diff_text.strip():
                candidate_status = "failed_no_patch"
                candidate_error = "Deterministic tests failed and the agent produced no code diff."
            else:
                candidate_status = "failed_tests"
                candidate_error = "Agent produced a patch, but deterministic tests still failed."

            (artifact_dir / "patch.diff").write_text(diff_text, encoding="utf-8")
            (artifact_dir / "tests.txt").write_text(test_output, encoding="utf-8")
            (artifact_dir / "agent.txt").write_text(agent_output, encoding="utf-8")
            (artifact_dir / "candidate_meta.json").write_text(
                json.dumps(
                    {
                        "candidate_id": candidate_id,
                        "ordinal": ordinal,
                        "strategy": strategy,
                        "agent_exit_code": agent_exit_code,
                        "agent_status": agent_status,
                        "candidate_status": candidate_status,
                        "test_exit_code": test_exit_code,
                    },
                    indent=2,
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            try:
                transcript = (
                    await gateway.read(handle, "/workspace/agent_transcript.json", max_bytes=2_000_000)
                ).decode("utf-8", errors="replace")
                (artifact_dir / "agent_transcript.json").write_text(transcript, encoding="utf-8")
            except Exception as exc:
                logger.warning("Candidate %s transcript was unavailable: %s", ordinal, exc)

            await self.db.execute(
                "UPDATE candidates SET status=?, test_exit_code=?, diff_text=?, test_output=?, agent_output=?, artifact_path=?, error=? WHERE id=?",
                (
                    candidate_status,
                    test_exit_code,
                    diff_text,
                    test_output,
                    agent_output,
                    str(artifact_dir),
                    candidate_error,
                    candidate_id,
                ),
            )
            return CandidateEvidence(
                candidate_id=candidate_id,
                ordinal=ordinal,
                test_exit_code=test_exit_code,
                diff_text=diff_text,
                test_output=test_output,
                agent_output=agent_output,
                agent_exit_code=agent_exit_code,
                agent_status=agent_status,
                strategy=strategy,
            )
        except Exception as exc:
            logger.exception("Candidate %s failed", ordinal)
            await self.db.execute(
                "UPDATE candidates SET status=?, error=? WHERE id=?",
                ("failed", str(exc), candidate_id),
            )
            return CandidateEvidence(
                candidate_id=candidate_id,
                ordinal=ordinal,
                test_exit_code=999,
                diff_text="",
                test_output="",
                agent_output=str(exc),
                agent_exit_code=999,
                agent_status="orchestrator_error",
                strategy=strategy,
            )

    async def _persist_scores(self, run_id: str, evidence: list[CandidateEvidence]) -> None:
        try:
            for item in evidence:
                await self.db.execute(
                    "UPDATE candidates SET deterministic_score=?, ai_score=?, final_score=?, rank=? WHERE id=?",
                    (item.deterministic_score, item.ai_score, item.final_score, item.rank, item.candidate_id),
                )
        except Exception:
            logger.exception("Persisting scores failed for %s", run_id)
            raise

    async def _set_run_status(self, run_id: str, status: str) -> None:
        await self.db.execute("UPDATE runs SET status=?, updated_at=? WHERE id=?", (status, utc_now(), run_id))

    async def _safe_delete(self, gateway: RuntaGateway, handle: RuntimeHandle) -> None:
        try:
            await gateway.delete(handle)
        except Exception:
            logger.exception("Cleanup failed for runtime %s", handle.name)

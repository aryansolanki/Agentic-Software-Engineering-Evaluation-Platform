from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from runta_agent_eval.core.config import Settings
from runta_agent_eval.runta.gateway import RuntaGateway

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class CandidateEvidence:
    candidate_id: str
    ordinal: int
    test_exit_code: int
    diff_text: str
    test_output: str
    agent_output: str
    deterministic_score: float = 0.0
    ai_score: float | None = None
    final_score: float = 0.0
    rank: int | None = None
    agent_exit_code: int | None = None
    agent_status: str = "unknown"
    strategy: str = ""

    @property
    def eligible(self) -> bool:
        """A candidate may win only if its deterministic validation passes."""
        return self.test_exit_code == 0


async def deterministic_score(candidate: CandidateEvidence) -> float:
    try:
        if candidate.test_exit_code != 0:
            return 0.0
        changed_lines = 0
        for line in candidate.diff_text.splitlines():
            if line.startswith(("+++", "---")):
                continue
            if line.startswith(("+", "-")):
                changed_lines += 1
        scope_penalty = min(changed_lines * 0.05, 12.0)
        return round(max(0.0, 100.0 - scope_penalty), 2)
    except Exception:
        logger.exception("Deterministic scoring failed")
        return 0.0


async def run_ai_judge(
    settings: Settings,
    gateway: RuntaGateway,
    run_id: str,
    task: str,
    candidates: list[CandidateEvidence],
    *,
    keep_runtime: bool,
    model: str | None = None,
) -> dict[str, Any]:
    handle = None
    try:
        handle = await gateway.create_runtime(
            f"rae-{run_id[:8]}-judge",
            allowed_hosts=["api.openai.com"],
            memory_mib=512,
            memory_max_mib=1024,
            with_openai_secret=True,
        )
        worker_path = Path(__file__).resolve().parents[1] / "workers" / "judge_worker.py"
        await gateway.upload(handle, worker_path, "/workspace/judge_worker.py")
        bundle = {
            "task": task,
            "model": model or settings.openai_model,
            "api_url": settings.openai_api_url,
            "candidates": [
                {
                    "candidate_id": c.candidate_id,
                    "ordinal": c.ordinal,
                    "test_exit_code": c.test_exit_code,
                    "eligible": c.eligible,
                    "agent_exit_code": c.agent_exit_code,
                    "agent_status": c.agent_status,
                    "strategy": c.strategy,
                    "deterministic_score": c.deterministic_score,
                    "diff": c.diff_text[-30000:],
                    "test_output": c.test_output[-10000:],
                }
                for c in candidates
            ],
        }
        await gateway.write(handle, "/workspace/judge_input.json", json.dumps(bundle, ensure_ascii=False))
        result = await gateway.exec(
            handle,
            "python3 /workspace/judge_worker.py /workspace/judge_input.json /workspace/judge_output.json",
            timeout=300,
        )
        raw = (await gateway.read(handle, "/workspace/judge_output.json", max_bytes=200000)).decode(
            "utf-8", errors="replace"
        )
        data = json.loads(raw)
        data["runtime_id"] = handle.id
        data["command_exit_code"] = getattr(result, "exit_code", None)
        return data
    except Exception as exc:
        logger.exception("AI judge failed")
        return {"status": "error", "message": str(exc), "ranking": []}
    finally:
        if handle is not None and not keep_runtime:
            try:
                await gateway.delete(handle)
            except Exception:
                logger.exception("Could not delete judge runtime")


async def apply_ai_ranking(candidates: list[CandidateEvidence], judge: dict[str, Any]) -> None:
    try:
        by_id = {c.candidate_id: c for c in candidates}
        for row in judge.get("ranking", []):
            candidate = by_id.get(str(row.get("candidate_id")))
            if candidate is None:
                continue
            try:
                candidate.ai_score = max(0.0, min(100.0, float(row.get("score", 0.0))))
            except (TypeError, ValueError):
                candidate.ai_score = 0.0
    except Exception:
        logger.exception("Applying AI ranking failed")


async def finalize_ranking(candidates: list[CandidateEvidence], mode: str) -> None:
    """Compute scores and rank passing candidates ahead of failing candidates.

    AI judgment can break ties or assess engineering quality, but deterministic
    correctness is always a hard eligibility boundary for winner selection.
    """
    try:
        for c in candidates:
            if mode == "deterministic":
                c.final_score = c.deterministic_score
            elif mode == "ai_judge":
                c.final_score = c.ai_score if c.ai_score is not None else c.deterministic_score
            else:
                if c.ai_score is None:
                    # Judge failure should degrade gracefully to objective evidence, not shrink scores by 35%.
                    c.final_score = c.deterministic_score
                else:
                    c.final_score = round(
                        (0.65 * c.deterministic_score) + (0.35 * c.ai_score),
                        2,
                    )

        ordered = sorted(
            candidates,
            key=lambda c: (
                1 if c.eligible else 0,
                c.final_score,
                c.deterministic_score,
                -(c.ordinal),
            ),
            reverse=True,
        )
        for index, candidate in enumerate(ordered, start=1):
            candidate.rank = index
    except Exception:
        logger.exception("Final ranking failed")
        raise


def select_winner(candidates: list[CandidateEvidence]) -> CandidateEvidence | None:
    eligible = [c for c in candidates if c.eligible]
    if not eligible:
        return None
    return min(eligible, key=lambda item: item.rank or 999999)

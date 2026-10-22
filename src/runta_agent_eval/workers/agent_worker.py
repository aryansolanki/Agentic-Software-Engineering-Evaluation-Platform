from __future__ import annotations

import asyncio
import hashlib
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Awaitable, Callable

ModelCaller = Callable[[str, str, str], Awaitable[str]]

SYSTEM = """You are an autonomous software engineer inside an isolated Runta runtime.
Solve the task by inspecting and editing the repository. Work surgically. Do not ask questions.

You have these actions and MUST return exactly one JSON object per turn:
{"action":"exec","command":"..."}
{"action":"read","path":"relative/path","max_chars":12000}
{"action":"write","path":"relative/path","content":"..."}
{"action":"replace","path":"relative/path","old":"exact text","new":"replacement text","count":1}
{"action":"finish","summary":"..."}

Output rules:
- Return only one valid JSON object and nothing else.
- Do not include markdown, code fences, comments, explanations, or trailing text.
- Use read for source/tests, exec for tests/search/git diff/listing, write for full-file replacement, and replace for a small exact edit.
- Never attempt to obtain credentials.
- Only touch files required by the task.
- When source code needs to change, you MUST use write or replace.
- Do not repeat the same failing test or inspection command without making progress.
- The harness independently validates the configured test command before accepting finish.
- If finish is rejected because tests fail, continue fixing the repository.
"""


def parse_action(raw: str) -> dict[str, Any]:
    """Extract the first JSON object containing an action field from model text."""
    text = raw.strip()

    if text.startswith("```json"):
        text = text[len("```json"):].strip()
        if text.endswith("```"):
            text = text[:-3].strip()
    elif text.startswith("```"):
        text = text[3:].strip()
        if text.endswith("```"):
            text = text[:-3].strip()

    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            obj, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and "action" in obj:
            return obj

    raise ValueError(f"No valid action JSON object found in model response: {raw[:500]}")


def _extract_text(payload: dict[str, Any]) -> str:
    if isinstance(payload.get("output_text"), str):
        return payload["output_text"]
    chunks: list[str] = []
    for item in payload.get("output", []) or []:
        for content in item.get("content", []) or []:
            text = content.get("text")
            if isinstance(text, str):
                chunks.append(text)
    return "\n".join(chunks)


def _call_model_sync(api_url: str, model: str, prompt: str) -> str:
    body = json.dumps({"model": model, "input": prompt}).encode("utf-8")
    request = urllib.request.Request(
        api_url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Model HTTP {exc.code}: {error_body[:5000]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Model network error: {exc}") from exc
    text = _extract_text(payload)
    if not text.strip():
        raise RuntimeError("Model response did not contain output text")
    return text


async def call_model(api_url: str, model: str, prompt: str) -> str:
    return await asyncio.to_thread(_call_model_sync, api_url, model, prompt)


def _safe_target(repo: Path, path: str) -> Path | None:
    repo_resolved = repo.resolve()
    target = (repo / path).resolve()
    if target == repo_resolved or repo_resolved not in target.parents:
        return None
    return target


async def exec_tool(repo: Path, command: str) -> str:
    def _run() -> str:
        try:
            completed = subprocess.run(
                command,
                cwd=repo,
                shell=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=180,
            )
            return f"exit={completed.returncode}\n{completed.stdout[-20000:]}"
        except subprocess.TimeoutExpired as exc:
            partial = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
            return f"exit=124\nCOMMAND TIMED OUT after 180s\n{partial[-10000:]}"

    return await asyncio.to_thread(_run)


async def read_tool(repo: Path, path: str, max_chars: int) -> str:
    target = _safe_target(repo, path)
    if target is None:
        return "ERROR: path escapes repository"
    if not target.exists() or not target.is_file():
        return "ERROR: file not found"
    return (await asyncio.to_thread(target.read_text, encoding="utf-8", errors="replace"))[:max_chars]


async def write_tool(repo: Path, path: str, content: str) -> str:
    target = _safe_target(repo, path)
    if target is None:
        return "ERROR: path escapes repository"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.is_file():
        current = await asyncio.to_thread(target.read_text, encoding="utf-8", errors="replace")
        if current == content:
            return "NO_CHANGE: requested write is identical to the current file; choose a different edit"
    await asyncio.to_thread(target.write_text, content, encoding="utf-8")
    return f"WROTE {path} ({len(content)} chars)"


async def replace_tool(repo: Path, path: str, old: str, new: str, count: int = 1) -> str:
    target = _safe_target(repo, path)
    if target is None:
        return "ERROR: path escapes repository"
    if not target.exists() or not target.is_file():
        return "ERROR: file not found"
    if not old:
        return "ERROR: old text must not be empty"
    if old == new:
        return "NO_CHANGE: replacement old/new text are identical"
    text = await asyncio.to_thread(target.read_text, encoding="utf-8", errors="replace")
    occurrences = text.count(old)
    if occurrences == 0:
        return "ERROR: exact old text was not found; read the file again before replacing"
    if count < 1:
        count = 1
    updated = text.replace(old, new, count)
    await asyncio.to_thread(target.write_text, updated, encoding="utf-8")
    return f"REPLACED {min(count, occurrences)} occurrence(s) in {path}"


def action_signature(action: dict[str, Any]) -> str:
    kind = str(action.get("action", ""))
    if kind == "exec":
        payload = str(action.get("command", "")).strip()
    elif kind == "read":
        payload = str(action.get("path", "")).strip()
    elif kind in {"write", "replace"}:
        content = str(action.get("content", action.get("new", "")))
        digest = hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()[:12]
        payload = f"{action.get('path', '')}:{digest}"
    else:
        payload = json.dumps(action, sort_keys=True, ensure_ascii=False)
    return f"{kind}:{payload}"


def should_block_repeat(
    action: dict[str, Any],
    *,
    test_command: str,
    edit_epoch: int,
    counts: dict[tuple[int, str], int],
) -> tuple[bool, str]:
    kind = str(action.get("action", ""))
    if kind not in {"exec", "read", "finish"}:
        return False, ""
    signature = action_signature(action)
    previous = counts.get((edit_epoch, signature), 0)
    threshold = 1 if kind == "finish" else 2
    if kind == "exec" and str(action.get("command", "")).strip() == test_command.strip():
        threshold = 1
    if previous >= threshold:
        if kind == "exec" and str(action.get("command", "")).strip() == test_command.strip():
            return True, (
                "LOOP_GUARD: You already ran the configured test command after the last edit. "
                "Do not rerun the same failing tests until you make a code change with write/replace, "
                "or inspect one specific file needed to determine that change."
            )
        return True, (
            "LOOP_GUARD: You have already repeated this action without an intervening edit. "
            "Choose a different inspection step or modify the relevant source with write/replace."
        )
    return False, ""


def _compact_action(action: dict[str, Any]) -> str:
    kind = str(action.get("action", ""))
    if kind == "exec":
        return f"exec {action.get('command', '')}"
    if kind == "read":
        return f"read {action.get('path', '')}"
    if kind == "write":
        return f"write {action.get('path', '')} ({len(str(action.get('content', '')))} chars)"
    if kind == "replace":
        return f"replace {action.get('path', '')}"
    if kind == "finish":
        return f"finish {action.get('summary', '')}"
    return json.dumps(action, ensure_ascii=False, sort_keys=True)


def build_working_state(transcript: list[dict[str, Any]]) -> str:
    files_read: list[str] = []
    files_changed: list[str] = []
    commands: list[str] = []
    loop_blocks = 0
    for row in transcript:
        action = row.get("action") or {}
        kind = action.get("action")
        if kind == "read":
            path = str(action.get("path", ""))
            if path and path not in files_read:
                files_read.append(path)
        elif kind in {"write", "replace"}:
            path = str(action.get("path", ""))
            if path and path not in files_changed:
                files_changed.append(path)
        elif kind == "exec":
            command = str(action.get("command", "")).strip()
            if command and command not in commands:
                commands.append(command)
        if row.get("loop_guard"):
            loop_blocks += 1

    return (
        f"Files already read: {files_read or ['none']}\n"
        f"Files modified: {files_changed or ['none']}\n"
        f"Commands already executed: {commands or ['none']}\n"
        f"Loop-guard interventions: {loop_blocks}\n"
    )


def format_recent_history(transcript: list[dict[str, Any]], max_chars: int = 36000) -> str:
    chunks: list[str] = []
    for row in transcript:
        if "action" in row:
            chunk = (
                f"STEP {row.get('step')}: {_compact_action(row['action'])}\n"
                f"RESULT:\n{str(row.get('tool_result', ''))[-12000:]}"
            )
        else:
            chunk = f"STEP {row.get('step')}: MODEL FORMAT ERROR\n{str(row.get('raw', ''))[-3000:]}"
        chunks.append(chunk)
    text = "\n\n".join(chunks)
    return text[-max_chars:] if text else "No previous actions yet."


def build_prompt(
    *,
    task: str,
    strategy: str,
    test_command: str,
    step: int,
    max_steps: int,
    transcript: list[dict[str, Any]],
    observation: str,
) -> str:
    return (
        f"{SYSTEM}\n\n"
        f"TASK:\n{task}\n\n"
        f"CANDIDATE STRATEGY:\n{strategy}\n\n"
        f"CONFIGURED TEST COMMAND:\n{test_command}\n"
        "Use this exact test command for verification. Do not substitute pytest, tox, or another test runner unless the configured command itself fails because the repository explicitly requires a different invocation.\n\n"
        f"STEP {step}/{max_steps}\n\n"
        f"KNOWN WORKING STATE:\n{build_working_state(transcript)}\n"
        f"RECENT ACTION/TOOL HISTORY:\n{format_recent_history(transcript)}\n\n"
        f"CURRENT OBSERVATION:\n{observation[-20000:]}\n\n"
        "Return the next single JSON action."
    )


def _write_transcript(path: Path, transcript: list[dict[str, Any]]) -> None:
    path.write_text(json.dumps(transcript, indent=2, ensure_ascii=False), encoding="utf-8")


async def run_agent_loop(
    *,
    repo: Path,
    task: str,
    model: str,
    api_url: str,
    max_steps: int,
    test_command: str,
    strategy: str,
    transcript_path: Path,
    model_caller: ModelCaller = call_model,
) -> int:
    transcript: list[dict[str, Any]] = []
    observation = "Start by inspecting the repository and the tests before making the smallest correct change."
    edit_epoch = 0
    action_counts: dict[tuple[int, str], int] = {}

    for step in range(1, max_steps + 1):
        prompt = build_prompt(
            task=task,
            strategy=strategy,
            test_command=test_command,
            step=step,
            max_steps=max_steps,
            transcript=transcript,
            observation=observation,
        )
        raw = await model_caller(api_url, model, prompt)
        try:
            action = parse_action(raw)
        except ValueError:
            observation = (
                "FORMAT_ERROR: Your last response did not contain one valid JSON action. "
                f"Return only one supported JSON action. Response was: {raw[:3000]}"
            )
            transcript.append({"step": step, "raw": raw, "error": "invalid_action_json", "tool_result": observation})
            continue

        row: dict[str, Any] = {"step": step, "action": action}
        transcript.append(row)
        kind = str(action.get("action", ""))

        blocked, reason = should_block_repeat(
            action,
            test_command=test_command,
            edit_epoch=edit_epoch,
            counts=action_counts,
        )
        signature = action_signature(action)
        action_counts[(edit_epoch, signature)] = action_counts.get((edit_epoch, signature), 0) + 1
        if blocked:
            observation = reason
            row["loop_guard"] = True
            row["tool_result"] = observation
            continue

        if kind == "finish":
            validation = await exec_tool(repo, test_command)
            row["finish_validation"] = validation[-20000:]
            if validation.startswith("exit=0\n"):
                observation = "FINISH_ACCEPTED: deterministic test command passed."
                row["tool_result"] = observation
                _write_transcript(transcript_path, transcript)
                print(json.dumps({
                    "status": "finished",
                    "summary": action.get("summary", ""),
                    "steps": step,
                    "tests_validated": True,
                }))
                return 0
            observation = (
                "FINISH_REJECTED: the configured deterministic tests still fail. "
                "Use the failure below, modify the repository with write/replace, then verify again.\n"
                + validation[-18000:]
            )
            row["tool_result"] = observation
            continue

        if kind == "exec":
            command = str(action.get("command", "")).strip()
            if not command:
                observation = "ERROR: exec requires a non-empty command"
            else:
                observation = await exec_tool(repo, command)
        elif kind == "read":
            observation = await read_tool(
                repo,
                str(action.get("path", "")),
                int(action.get("max_chars", 12000)),
            )
        elif kind == "write":
            observation = await write_tool(
                repo,
                str(action.get("path", "")),
                str(action.get("content", "")),
            )
            if not observation.startswith(("ERROR:", "NO_CHANGE:")):
                edit_epoch += 1
        elif kind == "replace":
            observation = await replace_tool(
                repo,
                str(action.get("path", "")),
                str(action.get("old", "")),
                str(action.get("new", "")),
                int(action.get("count", 1)),
            )
            if not observation.startswith(("ERROR:", "NO_CHANGE:")):
                edit_epoch += 1
        else:
            observation = f"ERROR: unknown action {kind!r}. Use exec, read, write, replace, or finish."

        row["tool_result"] = observation[-20000:]

    _write_transcript(transcript_path, transcript)
    print(json.dumps({"status": "max_steps", "steps": max_steps, "tests_validated": False}))
    return 2


async def main() -> int:
    repo = Path(os.environ.get("RAE_REPO", "/workspace/repo")).resolve()
    task_file = Path(os.environ.get("RAE_TASK_FILE", "/workspace/task.txt"))
    model = os.environ.get("RAE_MODEL", "gpt-5-mini")
    api_url = os.environ.get("RAE_API_URL", "https://api.openai.com/v1/responses")
    max_steps = int(os.environ.get("RAE_MAX_STEPS", "24"))
    test_command = os.environ.get("RAE_TEST_COMMAND", "python3 -m unittest -v").strip()
    strategy = os.environ.get(
        "RAE_STRATEGY",
        "Find the root cause, make the smallest correct patch, and verify the configured tests.",
    ).strip()
    transcript_path = Path(os.environ.get("RAE_TRANSCRIPT_PATH", "/workspace/agent_transcript.json"))
    task = task_file.read_text(encoding="utf-8")

    return await run_agent_loop(
        repo=repo,
        task=task,
        model=model,
        api_url=api_url,
        max_steps=max_steps,
        test_command=test_command,
        strategy=strategy,
        transcript_path=transcript_path,
    )


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except Exception as exc:
        print(json.dumps({"status": "error", "message": str(exc)}), file=sys.stderr)
        raise

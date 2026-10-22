import json
import shutil
import sys
from pathlib import Path

import pytest

TEST_COMMAND = f'"{sys.executable}" -m unittest -v'

from runta_agent_eval.workers.agent_worker import (
    action_signature,
    build_prompt,
    parse_action,
    replace_tool,
    run_agent_loop,
    should_block_repeat,
)


def test_parse_action_recovers_json_from_prose_and_fence():
    raw = 'I will inspect it.\n```json\n{"action":"read","path":"calc.py"}\n```'
    action = parse_action(raw)
    assert action == {"action": "read", "path": "calc.py"}


def test_prompt_contains_persistent_history():
    transcript = [
        {
            "step": 1,
            "action": {"action": "read", "path": "calc.py"},
            "tool_result": "def checkout(...): pass",
        },
        {
            "step": 2,
            "action": {"action": "exec", "command": TEST_COMMAND},
            "tool_result": "exit=1\nFAIL: test_discount_then_tax",
        },
    ]
    prompt = build_prompt(
        task="Fix the bug",
        strategy="Minimal fix",
        test_command=TEST_COMMAND,
        step=3,
        max_steps=24,
        transcript=transcript,
        observation="exit=1",
    )
    assert "read calc.py" in prompt
    assert "FAIL: test_discount_then_tax" in prompt
    assert "Minimal fix" in prompt
    assert TEST_COMMAND in prompt


@pytest.mark.asyncio
async def test_replace_tool_makes_small_exact_edit(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    target = repo / "a.py"
    target.write_text("value = 1\n", encoding="utf-8")
    result = await replace_tool(repo, "a.py", "value = 1", "value = 2")
    assert result.startswith("REPLACED")
    assert target.read_text(encoding="utf-8") == "value = 2\n"


def test_loop_guard_blocks_repeated_failing_test_until_edit():
    action = {"action": "exec", "command": TEST_COMMAND}
    sig = action_signature(action)
    counts = {(0, sig): 1}
    blocked, reason = should_block_repeat(
        action,
        test_command=TEST_COMMAND,
        edit_epoch=0,
        counts=counts,
    )
    assert blocked is True
    assert "LOOP_GUARD" in reason


@pytest.mark.asyncio
async def test_simulated_agent_solves_fixture_and_finish_is_validated(tmp_path: Path):
    source = Path(__file__).resolve().parents[1] / "fixtures" / "buggy_calc"
    repo = tmp_path / "repo"
    shutil.copytree(source, repo)
    transcript_path = tmp_path / "agent_transcript.json"

    responses = iter(
        [
            {"action": "read", "path": "test_calc.py"},
            {"action": "read", "path": "calc.py"},
            {"action": "exec", "command": TEST_COMMAND},
            {
                "action": "replace",
                "path": "calc.py",
                "old": "    taxed = subtotal * (1 + tax_pct / 100)\n    discounted = taxed * (1 - discount_pct / 100)\n    return round(discounted, 2)",
                "new": "    discounted = round(subtotal * (1 - discount_pct / 100), 2)\n    taxed = discounted * (1 + tax_pct / 100)\n    return round(taxed, 2)",
                "count": 1,
            },
            {"action": "exec", "command": TEST_COMMAND},
            {"action": "finish", "summary": "Fixed discount-before-tax rounding and verified tests."},
        ]
    )

    async def fake_model(_url: str, _model: str, prompt: str) -> str:
        # The prompt should retain prior tool state while the sequence progresses.
        if "STEP 4/12" in prompt:
            assert "FAIL" in prompt
            assert "calc.py" in prompt
        return json.dumps(next(responses))

    code = await run_agent_loop(
        repo=repo,
        task="Fix the calculator so discounts are applied before tax and tests pass.",
        model="fake",
        api_url="https://example.invalid",
        max_steps=12,
        test_command=TEST_COMMAND,
        strategy="Minimal root-cause strategy",
        transcript_path=transcript_path,
        model_caller=fake_model,
    )

    assert code == 0
    assert transcript_path.exists()
    transcript = json.loads(transcript_path.read_text(encoding="utf-8"))
    assert any(row.get("action", {}).get("action") == "replace" for row in transcript)
    assert transcript[-1].get("finish_validation", "").startswith("exit=0\n")

@pytest.mark.asyncio
async def test_finish_is_rejected_until_tests_pass(tmp_path: Path):
    source = Path(__file__).resolve().parents[1] / "fixtures" / "buggy_calc"
    repo = tmp_path / "repo"
    shutil.copytree(source, repo)
    transcript_path = tmp_path / "agent_transcript.json"

    responses = iter(
        [
            {"action": "finish", "summary": "Premature finish"},
            {
                "action": "replace",
                "path": "calc.py",
                "old": "    taxed = subtotal * (1 + tax_pct / 100)\n    discounted = taxed * (1 - discount_pct / 100)\n    return round(discounted, 2)",
                "new": "    discounted = round(subtotal * (1 - discount_pct / 100), 2)\n    taxed = discounted * (1 + tax_pct / 100)\n    return round(taxed, 2)",
            },
            {"action": "finish", "summary": "Now verified"},
        ]
    )

    async def fake_model(_url: str, _model: str, _prompt: str) -> str:
        return json.dumps(next(responses))

    code = await run_agent_loop(
        repo=repo,
        task="Fix the calculator",
        model="fake",
        api_url="https://example.invalid",
        max_steps=6,
        test_command=TEST_COMMAND,
        strategy="Minimal",
        transcript_path=transcript_path,
        model_caller=fake_model,
    )
    assert code == 0
    transcript = json.loads(transcript_path.read_text(encoding="utf-8"))
    assert "FINISH_REJECTED" in transcript[0]["tool_result"]
    assert transcript[-1]["finish_validation"].startswith("exit=0\n")

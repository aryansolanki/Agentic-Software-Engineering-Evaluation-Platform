from pathlib import Path

from runta_agent_eval.services.diffing import build_workspace_diff


def test_workspace_diff_detects_modified_file_and_ignores_cache(tmp_path: Path):
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    baseline.mkdir(); candidate.mkdir()
    (baseline / "calc.py").write_text("value = 1\n", encoding="utf-8")
    (candidate / "calc.py").write_text("value = 2\n", encoding="utf-8")
    (candidate / "__pycache__").mkdir()
    (candidate / "__pycache__" / "calc.pyc").write_bytes(b"noise")

    diff = build_workspace_diff(baseline, candidate)
    assert "diff --git a/calc.py b/calc.py" in diff
    assert "-value = 1" in diff
    assert "+value = 2" in diff
    assert "__pycache__" not in diff


def test_workspace_diff_detects_added_and_deleted_files(tmp_path: Path):
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    baseline.mkdir(); candidate.mkdir()
    (baseline / "old.txt").write_text("old\n", encoding="utf-8")
    (candidate / "new.txt").write_text("new\n", encoding="utf-8")

    diff = build_workspace_diff(baseline, candidate)
    assert "diff --git a/old.txt b/old.txt" in diff
    assert "diff --git a/new.txt b/new.txt" in diff
    assert "/dev/null" in diff

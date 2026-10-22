from runta_agent_eval.services.orchestrator import (
    extract_agent_status,
    strategy_for_candidate,
)


def test_candidate_strategies_are_distinct_for_first_three():
    strategies = {strategy_for_candidate(i) for i in range(1, 4)}
    assert len(strategies) == 3


def test_extract_agent_status_from_worker_output():
    output = 'some log\n{"status":"max_steps","steps":24}\n'
    assert extract_agent_status(output) == "max_steps"

from types import SimpleNamespace
import pytest
from runta_agent_eval.services.orchestrator import _require_success


def test_require_success_rejects_nonzero_repo_setup():
    result = SimpleNamespace(exit_code=7, stdout_text="", stderr_text="dependency install failed")
    with pytest.raises(RuntimeError, match="Repository setup command failed with exit code 7"):
        _require_success(result, "Repository setup command")

@pytest.mark.asyncio
async def test_fixture_baseline_does_not_require_git_snapshot(tmp_path, monkeypatch):
    from runta_agent_eval.services.orchestrator import Orchestrator
    from runta_agent_eval.core.models import SourceMode

    calls = []

    class FakeGateway:
        async def upload(self, handle, src, dst):
            calls.append(("upload", str(dst)))

        async def exec(self, handle, command, **kwargs):
            calls.append(("exec", command, kwargs.get("cwd")))
            return SimpleNamespace(exit_code=1, stdout_text="", stderr_text="expected failing baseline test")

    class FakeDB:
        async def add_observation(self, *args, **kwargs):
            pass

    settings = SimpleNamespace()
    orch = Orchestrator(settings, FakeDB())
    request = SimpleNamespace(
        source_mode=SourceMode.FIXTURE,
        setup_command="",
        test_command="python3 -m unittest -v",
    )
    await orch._prepare_baseline(FakeGateway(), object(), request)

    commands = [c[1] for c in calls if c[0] == "exec"]
    assert commands == ["python3 -m unittest -v"]
    assert not any("git init" in c or "git config" in c or "git commit" in c for c in commands)


def test_diffing_does_not_require_git_metadata(tmp_path):
    from runta_agent_eval.services.diffing import build_workspace_diff

    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    baseline.mkdir()
    candidate.mkdir()
    (baseline / "calc.py").write_text("x = 1\n", encoding="utf-8")
    (candidate / "calc.py").write_text("x = 2\n", encoding="utf-8")

    diff = build_workspace_diff(baseline, candidate)
    assert "diff --git a/calc.py b/calc.py" in diff
    assert "-x = 1" in diff
    assert "+x = 2" in diff



def test_remote_snapshot_script_excludes_virtualenv_and_symlinks(tmp_path):
    import subprocess
    import zipfile
    from pathlib import Path
    from runta_agent_eval.services.snapshot import REMOTE_SNAPSHOT_SCRIPT

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "src.py").write_text("print('ok')\n", encoding="utf-8")
    venv = repo / ".venv" / "bin"
    venv.mkdir(parents=True)
    (venv / "python3").write_text("binary-ish", encoding="utf-8")
    try:
        (venv / "python").symlink_to("python3")
    except OSError:
        pass
    cache = repo / "__pycache__"
    cache.mkdir()
    (cache / "x.pyc").write_bytes(b"abc")

    script = tmp_path / "snapshot.py"
    script.write_text(REMOTE_SNAPSHOT_SCRIPT, encoding="utf-8")
    archive = tmp_path / "snapshot.zip"
    subprocess.run(["python", str(script), str(repo), str(archive)], check=True)

    with zipfile.ZipFile(archive) as zf:
        names = set(zf.namelist())
    assert "src.py" in names
    assert not any(name.startswith(".venv/") for name in names)
    assert not any(name.startswith("__pycache__/") for name in names)


def test_extract_snapshot_zip_recreates_source_tree(tmp_path):
    import zipfile
    from runta_agent_eval.services.snapshot import extract_snapshot_zip

    archive = tmp_path / "source.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("pkg/core.py", "x = 1\n")
    out = tmp_path / "out"
    extract_snapshot_zip(archive, out)
    assert (out / "pkg" / "core.py").read_text(encoding="utf-8") == "x = 1\n"

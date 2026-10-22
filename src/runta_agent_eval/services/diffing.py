from __future__ import annotations

import difflib
from pathlib import Path

# Runtime/test byproducts that should never count as source patches.
_IGNORED_DIRS = {
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".tox",
    ".nox",
    ".venv",
    "venv",
    "node_modules",
}
_IGNORED_FILES = {".coverage", ".DS_Store"}
_IGNORED_SUFFIXES = {".pyc", ".pyo"}
_MAX_TEXT_BYTES = 2_000_000


def _should_ignore(rel: Path) -> bool:
    if any(part in _IGNORED_DIRS for part in rel.parts):
        return True
    if rel.name in _IGNORED_FILES:
        return True
    if rel.suffix in _IGNORED_SUFFIXES:
        return True
    return False


def _file_map(root: Path) -> dict[str, Path]:
    out: dict[str, Path] = {}
    if not root.exists():
        return out
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if _should_ignore(rel):
            continue
        out[rel.as_posix()] = path
    return out


def _read_bytes(path: Path | None) -> bytes:
    return b"" if path is None else path.read_bytes()


def _looks_binary(data: bytes) -> bool:
    return b"\x00" in data[:8192]


def build_workspace_diff(baseline: Path, candidate: Path) -> str:
    """Build a stable source diff without depending on remote Git metadata.

    Runta file downloads need not preserve `.git`, and agents are also free to run
    Git commands.  Comparing the prepared baseline snapshot to the downloaded
    candidate workspace makes exported patches deterministic and works for both
    the built-in fixture and public Git repositories.
    """
    before = _file_map(baseline)
    after = _file_map(candidate)
    chunks: list[str] = []

    for rel in sorted(set(before) | set(after)):
        old_path = before.get(rel)
        new_path = after.get(rel)
        old = _read_bytes(old_path)
        new = _read_bytes(new_path)
        if old == new:
            continue

        chunks.append(f"diff --git a/{rel} b/{rel}\n")
        if _looks_binary(old) or _looks_binary(new) or len(old) > _MAX_TEXT_BYTES or len(new) > _MAX_TEXT_BYTES:
            if old_path is None:
                chunks.append(f"Binary file b/{rel} added\n")
            elif new_path is None:
                chunks.append(f"Binary file a/{rel} deleted\n")
            else:
                chunks.append(f"Binary files a/{rel} and b/{rel} differ\n")
            continue

        old_text = old.decode("utf-8", errors="replace").splitlines(keepends=True)
        new_text = new.decode("utf-8", errors="replace").splitlines(keepends=True)
        fromfile = "/dev/null" if old_path is None else f"a/{rel}"
        tofile = "/dev/null" if new_path is None else f"b/{rel}"
        chunks.extend(
            difflib.unified_diff(
                old_text,
                new_text,
                fromfile=fromfile,
                tofile=tofile,
                lineterm="\n",
            )
        )

    return "".join(chunks)

from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

IGNORED_DIRS = {
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
IGNORED_FILES = {".coverage", ".DS_Store"}
IGNORED_SUFFIXES = {".pyc", ".pyo"}

# Runs inside a Runta runtime. It intentionally archives only ordinary files.
# Symlinks are skipped so the resulting archive is safe for the SDK downloader.
REMOTE_SNAPSHOT_SCRIPT = r'''from __future__ import annotations
import os
import sys
import zipfile
from pathlib import Path

root = Path(sys.argv[1]).resolve()
out = Path(sys.argv[2])
ignored_dirs = {".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox", ".nox", ".venv", "venv", "node_modules"}
ignored_files = {".coverage", ".DS_Store"}
ignored_suffixes = {".pyc", ".pyo"}
count = 0
with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
    for dirpath, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        base = Path(dirpath)
        kept_dirs = []
        for dirname in dirnames:
            p = base / dirname
            if dirname in ignored_dirs or p.is_symlink():
                continue
            kept_dirs.append(dirname)
        dirnames[:] = kept_dirs

        for filename in filenames:
            path = base / filename
            rel = path.relative_to(root)
            if filename in ignored_files or path.suffix in ignored_suffixes:
                continue
            if any(part in ignored_dirs for part in rel.parts):
                continue
            if path.is_symlink() or not path.is_file():
                continue
            zf.write(path, rel.as_posix())
            count += 1
print(f"snapshot_files={count}")
'''


def extract_snapshot_zip(archive: Path, destination: Path) -> None:
    """Extract a trusted source-only snapshot produced by REMOTE_SNAPSHOT_SCRIPT."""
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive, "r") as zf:
        root = destination.resolve()
        for info in zf.infolist():
            target = (destination / info.filename).resolve()
            if target != root and root not in target.parents:
                raise ValueError(f"unsafe snapshot member: {info.filename}")
        zf.extractall(destination)

from __future__ import annotations

import asyncio
import json
import logging
import shutil
from pathlib import Path

from runta_agent_eval.core.db import Database

logger = logging.getLogger(__name__)


async def build_export(db: Database, artifact_root: Path, run_id: str, mode: str) -> Path:
    try:
        data = await db.export_run(run_id)
        run = data.get("run") or {}
        candidates = data.get("candidates") or []
        winner_id = run.get("winner_candidate_id")
        if mode == "winner":
            selected = [c for c in candidates if c.get("id") == winner_id]
        elif mode == "nonwinners":
            selected = [c for c in candidates if c.get("id") != winner_id]
        elif mode == "all":
            selected = candidates
        else:
            selected = [c for c in candidates if c.get("id") == mode]
        if not selected:
            raise FileNotFoundError(f"No candidates available for export mode={mode}")

        export_dir = artifact_root / run_id / "exports" / mode
        if export_dir.exists():
            await asyncio.to_thread(shutil.rmtree, export_dir)
        export_dir.mkdir(parents=True, exist_ok=True)
        (export_dir / "summary.json").write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        for candidate in selected:
            src_text = candidate.get("artifact_path")
            if not src_text:
                continue
            src = Path(src_text)
            if src.exists():
                dst = export_dir / f"candidate-{candidate['ordinal']:02d}"
                await asyncio.to_thread(shutil.copytree, src, dst, dirs_exist_ok=True)
        zip_base = artifact_root / run_id / "exports" / f"{mode}-{run_id}"
        zip_path = await asyncio.to_thread(shutil.make_archive, str(zip_base), "zip", export_dir)
        return Path(zip_path)
    except Exception:
        logger.exception("Failed building export for run %s mode %s", run_id, mode)
        raise

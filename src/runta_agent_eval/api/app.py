from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse

from runta_agent_eval.core.config import load_settings
from runta_agent_eval.core.db import Database
from runta_agent_eval.core.models import StatusResponse, TaskCreate
from runta_agent_eval.services.exporter import build_export
from runta_agent_eval.services.orchestrator import Orchestrator, utc_now

logger = logging.getLogger(__name__)

settings = None
db = None
orchestrator = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global settings, db, orchestrator
    settings = await load_settings()
    settings.artifact_dir.mkdir(parents=True, exist_ok=True)
    settings.experiment_dir.mkdir(parents=True, exist_ok=True)
    db = Database(settings.database_path)
    await db.init()
    orchestrator = Orchestrator(settings, db)
    yield


app = FastAPI(title="Runta Agentic Software Engineering & Evaluation Platform", lifespan=lifespan)


@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    try:
        path = Path(__file__).resolve().parents[1] / "static" / "index.html"
        return HTMLResponse(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.exception("Failed serving dashboard")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/runs", response_model=StatusResponse)
async def create_run(request: TaskCreate) -> StatusResponse:
    try:
        assert orchestrator is not None
        run_id = await orchestrator.submit(request)
        return StatusResponse(status="accepted", message="Run queued", id=run_id)
    except Exception as exc:
        logger.exception("Run creation failed")
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/runs")
async def list_runs() -> list[dict]:
    try:
        assert db is not None
        return await db.fetchall("SELECT id,created_at,updated_at,status,name,candidate_count,evaluation_mode,winner_candidate_id,error FROM runs ORDER BY created_at DESC LIMIT 50")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/runs/{run_id}")
async def get_run(run_id: str) -> dict:
    try:
        assert db is not None
        data = await db.export_run(run_id)
        if data.get("run") is None:
            raise HTTPException(status_code=404, detail="Run not found")
        return data
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/observations", response_model=StatusResponse)
async def add_observation(payload: dict) -> StatusResponse:
    try:
        assert db is not None
        await db.add_observation(
            utc_now(),
            str(payload.get("category", "experience")),
            str(payload.get("title", "Untitled observation")),
            str(payload.get("details", "")),
            str(payload.get("run_id")) if payload.get("run_id") else None,
        )
        return StatusResponse(status="ok", message="Observation recorded")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/runs/{run_id}/download/{mode}")
async def download(run_id: str, mode: str) -> FileResponse:
    try:
        assert db is not None and settings is not None
        path = await build_export(db, settings.artifact_dir, run_id, mode)
        return FileResponse(path, filename=path.name, media_type="application/zip")
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import httpx

from runta_agent_eval.core.config import Settings
from runta_agent_eval.runta.gateway import RuntaGateway

logger = logging.getLogger(__name__)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def write_result(settings: Settings, name: str, payload: dict) -> None:
    try:
        settings.experiment_dir.mkdir(parents=True, exist_ok=True)
        path = settings.experiment_dir / f"{name}.json"
        await asyncio.to_thread(path.write_text, json.dumps(payload, indent=2, ensure_ascii=False), "utf-8")
    except Exception:
        logger.exception("Could not write experiment result")


async def preflight(settings: Settings) -> dict:
    result = {"experiment": "preflight", "started_at": now(), "status": "error"}
    try:
        if not settings.runta_token:
            raise RuntimeError("RUNTA_TOKEN is missing")
        async with RuntaGateway(settings) as gateway:
            result["health"] = await gateway.health()
            result["runtime_count"] = len(await gateway.list_runtimes())
        result["status"] = "ok"
    except Exception as exc:
        result["message"] = str(exc)
    result["finished_at"] = now()
    await write_result(settings, "preflight", result)
    return result


async def level1(settings: Settings) -> dict:
    result = {"experiment": "level1", "started_at": now(), "status": "error"}
    handle = None
    try:
        async with RuntaGateway(settings) as gateway:
            handle = await gateway.create_runtime("rae-level1", allowed_hosts=[])
            a = await gateway.exec(handle, "python3 -c 'print(\"RUNTA_LEVEL1_OK\")'")
            await gateway.write(handle, "/workspace/persist.txt", "persistent-marker")
            b = (await gateway.read(handle, "/workspace/persist.txt")).decode()
            result.update({"runtime_id": handle.id, "stdout": getattr(a, "stdout_text", ""), "file_value": b, "status": "ok"})
            if not settings.runta_keep_runtimes:
                await gateway.delete(handle)
                handle = None
    except Exception as exc:
        result["message"] = str(exc)
    result["finished_at"] = now()
    await write_result(settings, "level1", result)
    return result


async def level2(settings: Settings, forks: int = 3) -> dict:
    result = {"experiment": "level2", "started_at": now(), "forks": forks, "status": "error"}
    base = None
    children = []
    try:
        async with RuntaGateway(settings) as gateway:
            base = await gateway.create_runtime("rae-level2-base", allowed_hosts=[])
            await gateway.write(base, "/workspace/baseline.txt", "same-for-every-fork")
            cp = await gateway.checkpoint(base, "rae-level2-checkpoint")
            children = await asyncio.gather(*[
                gateway.create_runtime(f"rae-level2-c{i}", checkpoint_id=cp.id, allowed_hosts=[])
                for i in range(1, forks + 1)
            ])
            checks = []
            for i, child in enumerate(children, start=1):
                before = (await gateway.read(child, "/workspace/baseline.txt")).decode()
                await gateway.write(child, f"/workspace/only-{i}.txt", f"child-{i}")
                checks.append({"runtime_id": child.id, "baseline": before})
            result.update({"checkpoint_id": str(cp.id), "children": checks, "status": "ok"})
            if not settings.runta_keep_runtimes:
                await asyncio.gather(*(gateway.delete(child) for child in children))
                await gateway.delete(base)
                children, base = [], None
    except Exception as exc:
        result["message"] = str(exc)
    result["finished_at"] = now()
    await write_result(settings, "level2", result)
    return result


async def level3(settings: Settings, workers: int = 4) -> dict:
    result = {"experiment": "level3", "started_at": now(), "workers": workers, "status": "error"}
    base = None
    children = []
    try:
        async with RuntaGateway(settings) as gateway:
            base = await gateway.create_runtime("rae-level3-base", allowed_hosts=[])
            await gateway.write(base, "/workspace/base.txt", "fanout")
            cp = await gateway.checkpoint(base, "rae-level3-ready")
            children = await asyncio.gather(*[
                gateway.create_runtime(f"rae-level3-c{i}", checkpoint_id=cp.id, allowed_hosts=[])
                for i in range(1, workers + 1)
            ])
            commands = await asyncio.gather(*[
                gateway.exec(child, f"python3 -c 'import hashlib; print(hashlib.sha256(b\"worker-{i}\").hexdigest())'", timeout=60)
                for i, child in enumerate(children, start=1)
            ])
            result["outputs"] = [getattr(cmd, "stdout_text", "").strip() for cmd in commands]
            result["runtime_ids"] = [child.id for child in children]
            result["status"] = "ok"
            if not settings.runta_keep_runtimes:
                await asyncio.gather(*(gateway.delete(child) for child in children))
                await gateway.delete(base)
                children, base = [], None
    except Exception as exc:
        result["message"] = str(exc)
    result["finished_at"] = now()
    await write_result(settings, "level3", result)
    return result


async def level4(settings: Settings) -> dict:
    result = {"experiment": "level4", "started_at": now(), "status": "error", "checks": {}}
    handle = None
    try:
        async with RuntaGateway(settings) as gateway:
            handle = await gateway.create_runtime("rae-level4", allowed_hosts=["example.com"])
            try:
                failed = await gateway.exec(handle, "sh -lc 'exit 7'")
                result["checks"]["intentional_failure"] = {"exit_code": getattr(failed, "exit_code", None)}
            except Exception as exc:
                result["checks"]["intentional_failure"] = {"exception": str(exc)}
            try:
                await gateway.exec(handle, "python3 -c 'import time; time.sleep(10)'", timeout=1)
                result["checks"]["timeout"] = "unexpected_success"
            except Exception as exc:
                result["checks"]["timeout"] = str(exc)
            allowed = await gateway.exec(handle, "python3 -c \"import urllib.request; print(urllib.request.urlopen('https://example.com', timeout=10).status)\"", timeout=30)
            result["checks"]["allowed_egress"] = getattr(allowed, "stdout_text", "")
            try:
                blocked = await gateway.exec(handle, "python3 -c \"import urllib.request; print(urllib.request.urlopen('https://example.org', timeout=10).status)\"", timeout=30)
                result["checks"]["blocked_egress"] = getattr(blocked, "stdout_text", "")
            except Exception as exc:
                result["checks"]["blocked_egress"] = str(exc)
            await gateway.pause(handle)
            await gateway.resume(handle)
            await gateway.resize_memory(handle, min(settings.runta_memory_max_mib, settings.runta_memory_mib + 256))
            await gateway.shutdown(handle)
            await gateway.boot(handle)
            result["status"] = "ok"
            result["runtime_id"] = handle.id
            if not settings.runta_keep_runtimes:
                await gateway.delete(handle)
                handle = None
    except Exception as exc:
        result["message"] = str(exc)
    result["finished_at"] = now()
    await write_result(settings, "level4", result)
    return result


async def memory_auto(settings: Settings) -> dict:
    result = {"experiment": "memory-auto", "started_at": now(), "status": "error"}
    handle = None
    try:
        async with RuntaGateway(settings) as gateway:
            handle = await gateway.create_runtime(
                "rae-memory-auto",
                allowed_hosts=[],
                memory_mib=1024,
                memory_max_mib=2048,
            )
            script = r'''import time
blocks=[]
for i in range(18):
    blocks.append(bytearray(64*1024*1024))
    for p in range(0,len(blocks[-1]),4096): blocks[-1][p]=1
    print(f"allocated_mib={(i+1)*64}", flush=True)
    time.sleep(2)
time.sleep(15)
'''
            await gateway.write(handle, "/workspace/memory_pressure.py", script)
            before = await gateway.refresh(handle)
            try:
                pressure = await gateway.exec(handle, "python3 /workspace/memory_pressure.py", timeout=90)
                pressure_text = getattr(pressure, "stdout_text", "")
            except Exception as exc:
                pressure_text = f"ERROR: {exc}"
            after = await gateway.refresh(handle)
            result.update({
                "runtime_id": handle.id,
                "before": str(before),
                "after": str(after),
                "pressure_output": pressure_text,
                "status": "ok",
            })
            if not settings.runta_keep_runtimes:
                await gateway.delete(handle)
                handle = None
    except Exception as exc:
        result["message"] = str(exc)
    result["finished_at"] = now()
    await write_result(settings, "memory-auto", result)
    return result


async def autosuspend(settings: Settings) -> dict:
    result = {"experiment": "autosuspend", "started_at": now(), "status": "error"}
    handle = None
    try:
        async with RuntaGateway(settings) as gateway:
            handle = await gateway.create_runtime(
                "rae-autosuspend",
                allowed_hosts=[],
                ingress_port=8080,
                idle_suspend_after_secs=30,
                memory_mib=512,
                memory_max_mib=512,
            )
            await gateway.exec(handle, "sh -lc 'nohup python3 -m http.server 8080 >/tmp/http.log 2>&1 &'", timeout=30)
            # Official docs show both <port>-<runtime_id>.runta.dev on Publish a Service and
            # <runtime_id>.runta.dev on Auto Suspend. Probe both and record what actually works.
            urls = [f"https://8080-{handle.id}.runta.dev", f"https://{handle.id}.runta.dev"]
            probes = {}
            async with httpx.AsyncClient(timeout=45, follow_redirects=True) as client:
                for url in urls:
                    try:
                        response = await client.get(url)
                        probes[url] = {"status_code": response.status_code, "length": len(response.content)}
                    except Exception as exc:
                        probes[url] = {"error": str(exc)}
            await asyncio.sleep(105)
            after_idle = await gateway.refresh(handle)
            wake = {}
            async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
                for url in urls:
                    try:
                        response = await client.get(url)
                        wake[url] = {"status_code": response.status_code, "length": len(response.content)}
                    except Exception as exc:
                        wake[url] = {"error": str(exc)}
            after_wake = await gateway.refresh(handle)
            result.update({"runtime_id": handle.id, "initial_probes": probes, "after_idle": str(after_idle), "wake_probes": wake, "after_wake": str(after_wake), "status": "ok"})
            if not settings.runta_keep_runtimes:
                await gateway.delete(handle)
                handle = None
    except Exception as exc:
        result["message"] = str(exc)
    result["finished_at"] = now()
    await write_result(settings, "autosuspend", result)
    return result


async def cleanup(settings: Settings, execute: bool = False) -> dict:
    result = {"experiment": "cleanup", "started_at": now(), "execute": execute, "status": "error"}
    try:
        async with RuntaGateway(settings) as gateway:
            runtimes = await gateway.list_runtimes()
            checkpoints = await gateway.list_checkpoints()
            project_runtimes = [r for r in runtimes if str(getattr(r, "name", "")).startswith("rae-")]
            project_checkpoints = [
                cp for cp in checkpoints
                if str(getattr(cp, "display_name", "") or "").startswith("rae-")
            ]
            result["runtimes"] = [{"id": str(getattr(r, "id", "")), "name": str(getattr(r, "name", ""))} for r in project_runtimes]
            result["checkpoints"] = [{"id": str(getattr(cp, "id", "")), "name": str(getattr(cp, "display_name", ""))} for cp in project_checkpoints]
            if execute:
                for runtime in project_runtimes:
                    try:
                        await runtime.delete()
                    except Exception as exc:
                        result.setdefault("delete_errors", []).append({"runtime": str(getattr(runtime, "name", "")), "error": str(exc)})
                for cp in project_checkpoints:
                    try:
                        await gateway.delete_checkpoint(str(cp.id))
                    except Exception as exc:
                        result.setdefault("delete_errors", []).append({"checkpoint": str(getattr(cp, "display_name", "")), "error": str(exc)})
            result["status"] = "ok"
    except Exception as exc:
        result["message"] = str(exc)
    result["finished_at"] = now()
    await write_result(settings, "cleanup", result)
    return result

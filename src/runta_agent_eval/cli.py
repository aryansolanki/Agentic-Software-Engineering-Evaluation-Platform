from __future__ import annotations

import argparse
import asyncio
import json
import logging

import uvicorn

from runta_agent_eval.core.config import load_settings
from runta_agent_eval.core.logging import configure_logging
from runta_agent_eval.experiments import autosuspend, cleanup, level1, level2, level3, level4, memory_auto, preflight

logger = logging.getLogger(__name__)


async def _run_experiment(args: argparse.Namespace) -> None:
    try:
        await configure_logging()
        settings = await load_settings()
        if args.command == "preflight":
            result = await preflight(settings)
        elif args.command == "level1":
            result = await level1(settings)
        elif args.command == "level2":
            result = await level2(settings, args.forks)
        elif args.command == "level3":
            result = await level3(settings, args.workers)
        elif args.command == "level4":
            result = await level4(settings)
        elif args.command == "memory-auto":
            result = await memory_auto(settings)
        elif args.command == "autosuspend":
            result = await autosuspend(settings)
        elif args.command == "cleanup":
            result = await cleanup(settings, execute=args.execute)
        else:
            raise ValueError(f"Unsupported experiment {args.command}")
        print(json.dumps(result, indent=2, ensure_ascii=False))
    except Exception:
        logger.exception("CLI experiment failed")
        raise


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="runta-eval")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("preflight")
    sub.add_parser("level1")
    p2 = sub.add_parser("level2"); p2.add_argument("--forks", type=int, default=3)
    p3 = sub.add_parser("level3"); p3.add_argument("--workers", type=int, default=4)
    sub.add_parser("level4")
    sub.add_parser("memory-auto")
    sub.add_parser("autosuspend")
    pc = sub.add_parser("cleanup"); pc.add_argument("--execute", action="store_true", help="Actually delete project-owned rae-* runtimes/checkpoints. Without this flag it is a dry run.")
    sub.add_parser("serve")
    return p


def main() -> None:
    args = parser().parse_args()
    if args.command == "serve":
        async def _settings():
            await configure_logging()
            return await load_settings()
        settings = asyncio.run(_settings())
        uvicorn.run("runta_agent_eval.api.app:app", host=settings.app_host, port=settings.app_port, reload=False)
        return
    asyncio.run(_run_experiment(args))


if __name__ == "__main__":
    main()

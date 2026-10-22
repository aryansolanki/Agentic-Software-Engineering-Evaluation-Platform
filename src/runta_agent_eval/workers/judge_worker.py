from __future__ import annotations

import asyncio
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


def _extract_text(payload: dict[str, Any]) -> str:
    if isinstance(payload.get("output_text"), str):
        return payload["output_text"]
    chunks: list[str] = []
    for item in payload.get("output", []) or []:
        for content in item.get("content", []) or []:
            if isinstance(content.get("text"), str):
                chunks.append(content["text"])
    return "\n".join(chunks)


def _call_sync(url: str, model: str, prompt: str) -> str:
    data = json.dumps({"model": model, "input": prompt}).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST", headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as response:
            text = _extract_text(json.loads(response.read().decode("utf-8")))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Judge model HTTP {exc.code}: {body[:5000]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Judge model network error: {exc}") from exc
    if not text.strip():
        raise RuntimeError("Judge model response did not contain output text")
    return text


def _extract_json_object(raw: str) -> dict[str, Any]:
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
        if isinstance(obj, dict):
            return obj
    raise ValueError("judge returned no valid JSON object")


def _normalize_judgment(parsed: dict[str, Any], candidate_ids: list[str]) -> dict[str, Any]:
    rows = parsed.get("ranking")
    if not isinstance(rows, list):
        raise ValueError("judge JSON must contain a ranking list")

    seen: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        candidate_id = str(row.get("candidate_id", ""))
        if candidate_id not in candidate_ids or candidate_id in seen:
            continue
        try:
            score = float(row.get("score", 0.0))
        except (TypeError, ValueError):
            score = 0.0
        score = max(0.0, min(100.0, score))
        normalized.append({
            "candidate_id": candidate_id,
            "score": score,
            "reason": str(row.get("reason", ""))[:2000],
        })
        seen.add(candidate_id)

    for candidate_id in candidate_ids:
        if candidate_id not in seen:
            normalized.append({
                "candidate_id": candidate_id,
                "score": 0.0,
                "reason": "Judge omitted this candidate; normalized to score 0.",
            })

    normalized.sort(key=lambda row: row["score"], reverse=True)
    return {
        "status": "ok",
        "ranking": normalized,
        "overall_reason": str(parsed.get("overall_reason", ""))[:5000],
    }


async def main(input_path: str, output_path: str) -> int:
    bundle = json.loads(Path(input_path).read_text(encoding="utf-8"))
    prompt = """Act as a senior software-engineering evaluator. Compare candidates for the exact task below.
Correctness is primary. A candidate whose deterministic tests fail is not an acceptable winner, regardless of style.
Penalize regressions, unrelated changes, unnecessary complexity, brittle fixes, task mismatch, and agent failure states.
Use test evidence as evidence, then assess code quality among candidates that are functionally correct.
Return ONLY JSON in this exact shape:
{"ranking":[{"candidate_id":"...","score":0-100,"reason":"short reason"}],"overall_reason":"..."}
Every candidate must appear exactly once, highest score first.

""" + json.dumps(bundle, ensure_ascii=False)

    raw = await asyncio.to_thread(_call_sync, bundle["api_url"], bundle["model"], prompt)
    try:
        parsed = _extract_json_object(raw)
        result = _normalize_judgment(
            parsed,
            [str(c["candidate_id"]) for c in bundle.get("candidates", [])],
        )
    except (ValueError, TypeError) as exc:
        result = {
            "status": "error",
            "message": str(exc),
            "raw": raw,
            "ranking": [],
        }

    Path(output_path).write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0 if result.get("status") == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1], sys.argv[2])))

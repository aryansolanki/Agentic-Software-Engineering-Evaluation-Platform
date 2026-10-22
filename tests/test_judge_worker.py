from runta_agent_eval.workers.judge_worker import _extract_json_object, _normalize_judgment


def test_judge_parser_recovers_json_and_normalizes_candidates():
    raw = 'Here is the result:\n```json\n{"ranking":[{"candidate_id":"b","score":120,"reason":"best"}],"overall_reason":"ok"}\n```'
    parsed = _extract_json_object(raw)
    result = _normalize_judgment(parsed, ["a", "b"])
    assert result["status"] == "ok"
    assert result["ranking"][0]["candidate_id"] == "b"
    assert result["ranking"][0]["score"] == 100.0
    assert {row["candidate_id"] for row in result["ranking"]} == {"a", "b"}

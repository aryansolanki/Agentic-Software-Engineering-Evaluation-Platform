from runta_agent_eval.services.evaluation import (
    CandidateEvidence,
    deterministic_score,
    finalize_ranking,
    select_winner,
)


async def test_failed_candidate_scores_zero():
    c = CandidateEvidence("x", 1, 1, "+bad", "", "")
    assert await deterministic_score(c) == 0.0


async def test_passing_candidate_scores_positive():
    c = CandidateEvidence("x", 1, 0, "--- a/x\n+++ b/x\n+one\n-two", "", "")
    assert await deterministic_score(c) > 90


async def test_hybrid_ranking():
    a = CandidateEvidence("a", 1, 0, "", "", "", deterministic_score=100, ai_score=70)
    b = CandidateEvidence("b", 2, 0, "", "", "", deterministic_score=95, ai_score=95)
    await finalize_ranking([a, b], "hybrid")
    assert b.rank == 1


async def test_passing_candidate_always_ranks_above_failed_candidate():
    passing = CandidateEvidence("pass", 1, 0, "", "", "", deterministic_score=90, ai_score=10)
    failing = CandidateEvidence("fail", 2, 1, "", "", "", deterministic_score=0, ai_score=100)
    await finalize_ranking([failing, passing], "ai_judge")
    assert passing.rank == 1
    assert select_winner([failing, passing]) is passing


async def test_no_winner_when_all_candidates_fail():
    a = CandidateEvidence("a", 1, 1, "", "", "", deterministic_score=0, ai_score=80)
    b = CandidateEvidence("b", 2, 2, "", "", "", deterministic_score=0, ai_score=90)
    await finalize_ranking([a, b], "hybrid")
    assert select_winner([a, b]) is None

from runta_agent_eval.core.models import EvaluationMode, SourceMode, TaskCreate


def test_three_evaluation_modes():
    assert {m.value for m in EvaluationMode} == {"deterministic", "ai_judge", "hybrid"}


def test_candidate_count_configurable():
    task = TaskCreate(name="x", task="fix the failing test", candidate_count=8)
    assert task.candidate_count == 8
    assert task.source_mode == SourceMode.FIXTURE

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, model_validator


class EvaluationMode(str, Enum):
    DETERMINISTIC = "deterministic"
    AI_JUDGE = "ai_judge"
    HYBRID = "hybrid"


class SourceMode(str, Enum):
    FIXTURE = "fixture"
    GIT = "git"


class TaskCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    task: str = Field(min_length=5, max_length=6000)
    candidate_count: int = Field(default=3, ge=1, le=12)
    evaluation_mode: EvaluationMode = EvaluationMode.HYBRID
    source_mode: SourceMode = SourceMode.FIXTURE
    git_url: HttpUrl | None = None
    setup_command: str = ""
    test_command: str = "python3 -m unittest -v"
    model: str | None = None
    allowed_hosts: list[str] = Field(default_factory=list)
    keep_runtimes: bool = True

    @model_validator(mode="after")
    def validate_source(self):
        if self.source_mode == SourceMode.GIT and self.git_url is None:
            raise ValueError("git_url is required when source_mode=git")
        return self



class StatusResponse(BaseModel):
    status: Literal["ok", "error", "accepted"]
    message: str
    id: str | None = None

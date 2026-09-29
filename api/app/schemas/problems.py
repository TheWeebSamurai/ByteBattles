from pydantic import BaseModel, ConfigDict, field_validator, model_validator
from typing import Dict, List

from shared.models import Difficulty

class ProblemResponse(BaseModel):
    id: str
    title: str
    difficulty: Difficulty
    tags: List[str]
    accepted_submissions: int


class ProblemListResponse(BaseModel):
    items: List[ProblemResponse]
    total: int
    page: int
    limit: int
    has_more: bool

class ProblemDetailResponse(ProblemResponse):
    description: str
    constraints: List[str]
    input_desc: str
    output_desc: str
    sample_io: Dict[str, str]
    explanation: str | None

    memory_limit_mb: int
    time_limit_sec: int

    source: str | None
    editorial: str | None
    visibility: bool

class ProblemArrayDataValidator(BaseModel):
    tags: List[str]
    constraints: List[str]
    sample_io: Dict[str, str]

class ProblemUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    difficulty: Difficulty | None = None
    description: str | None = None
    constraints: List[str] | None = None
    input_desc: str | None = None
    output_desc: str | None = None
    sample_io: Dict[str, str] | None = None
    explanation: str | None = None
    memory_limit_mb: int | None = None
    time_limit_sec: int | None = None
    tags: List[str] | None = None
    visibility: bool | None = None
    source: str | None = None
    editorial: str | None = None

    @field_validator("tags")
    @classmethod
    def validate_unique_tags(cls, value):
        if value is not None and len(value) != len(set(value)):
            raise ValueError("tags must not contain duplicates")
        return value

    @model_validator(mode="after")
    def reject_null_required_fields(self):
        nullable_fields = {"explanation", "source", "editorial"}
        for field_name in self.model_fields_set - nullable_fields:
            if getattr(self, field_name) is None:
                raise ValueError(f"{field_name} cannot be null")
        return self

class TagCreate(BaseModel):
    name: str
    slug: str

class ProblemCreateResponse(BaseModel):
    id: str
    title: str
    difficulty: Difficulty
    tags: List[str]
    testcases: int

class TestCaseSetResponse(BaseModel):
    problem_id: str
    testcases: int
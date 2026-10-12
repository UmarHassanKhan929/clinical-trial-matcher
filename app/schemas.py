from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    """snake_case in Python, camelCase on the wire (matches FHIR conventions)."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

class Verdict(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    POTENTIAL = "POTENTIAL"
    INELIGIBLE = "INELIGIBLE"

class Status(str, Enum):
    """Whether the patient satisfies the requirement for eligibility.

    For an INCLUSION line: MET means the patient has the required property.
    For an EXCLUSION line: MET means the patient does NOT have the excluded property.
    """

    MET = "MET"
    NOT_MET = "NOT_MET"
    UNKNOWN = "UNKNOWN"

class CriterionType(str, Enum):
    INCLUSION = "INCLUSION"
    EXCLUSION = "EXCLUSION"

class CriterionResult(CamelModel):
    type: CriterionType
    text: str
    status: Status
    evidence: str

class GateResult(CamelModel):
    name: str
    passed: bool
    evidence: str

class MatchResult(CamelModel):
    nct_id: str
    title:str
    verdict: Verdict
    score:float=Field(ge=0.0,le=1.0)
    hard_gates_passed: bool
    gates:list[GateResult]
    criteria:list[CriterionResult]

class MatchRequest(CamelModel):
    bundle: dict[str, Any] = Field(description="FHIR R4 Bundle: one Patient + Conditions + Observations")
    as_of: date | None = Field(
        default=None,
        description="Reference date for age/recency. Pass it for reproducible audit runs.",
    )


class MatchResponse(CamelModel):
    patient_id: str
    as_of: date
    results: list[MatchResult]


class RegistrationRequest(CamelModel):
    patient_id: str = Field(min_length=1)
    nct_id: str = Field(pattern=r"^NCT\d{8}$")
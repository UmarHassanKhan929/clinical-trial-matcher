"""FR-5: roll criterion statuses up into one verdict and a 0.0-1.0 score."""

from __future__ import annotations

from .schemas import CriterionResult, Status, Verdict


def roll_up(criteria: list[CriterionResult]) -> tuple[Verdict, float]:
    """Verdict: any NOT_MET -> INELIGIBLE; else any UNKNOWN -> POTENTIAL; else ELIGIBLE.

    Score: MET counts 1, UNKNOWN counts 0.5, NOT_MET counts 0, divided by the number of
    criteria. Integer arithmetic until the final division keeps it reproducible.
    No parsable criteria means no evidence either way: POTENTIAL with a neutral 0.5.
    """
    n = len(criteria)
    if n == 0:
        return Verdict.POTENTIAL, 0.5
    met = sum(c.status is Status.MET for c in criteria)
    unknown = sum(c.status is Status.UNKNOWN for c in criteria)
    not_met = n - met - unknown
    score = round((2 * met + unknown) / (2 * n), 2)
    if not_met:
        return Verdict.INELIGIBLE, score
    return (Verdict.POTENTIAL if unknown else Verdict.ELIGIBLE), score

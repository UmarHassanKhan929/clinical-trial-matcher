from app.schemas import CriterionResult, CriterionType, Status, Verdict
from app.scoring import roll_up


def crit(status):
    return CriterionResult(type=CriterionType.INCLUSION, text="x", status=status, evidence="e")


def test_all_met_is_eligible():
    assert roll_up([crit(Status.MET)] * 3) == (Verdict.ELIGIBLE, 1.0)


def test_unknown_makes_potential_and_counts_half():
    assert roll_up([crit(Status.MET), crit(Status.UNKNOWN)]) == (Verdict.POTENTIAL, 0.75)


def test_any_not_met_is_ineligible():
    verdict, score = roll_up([crit(Status.MET), crit(Status.NOT_MET), crit(Status.UNKNOWN)])
    assert verdict is Verdict.INELIGIBLE
    assert score == 0.5  # (2*1 + 1) / 6


def test_not_met_beats_unknown():
    assert roll_up([crit(Status.UNKNOWN), crit(Status.NOT_MET)])[0] is Verdict.INELIGIBLE


def test_no_criteria_is_potential_neutral():
    assert roll_up([]) == (Verdict.POTENTIAL, 0.5)

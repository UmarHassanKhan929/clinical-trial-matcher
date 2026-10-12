"""FR-4 Stage 2: split eligibility text into lines and tag each with deterministic regex rules.

Design rules (all deliberate, all deterministic):
  * First rule that understands a line wins: age -> lab threshold -> condition -> fallback.
  * Anything we cannot evaluate with confidence is UNKNOWN (never a guess).
  * Status is "does the patient satisfy the requirement?": for EXCLUSION lines MET means
    the patient does NOT have the excluded property.
"""

from __future__ import annotations

import operator
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from .patient import PatientProfile
from .schemas import CriterionResult, CriterionType, Status
from .vocab import LABS, Disease, find_diseases

MAX_LAB_AGE_DAYS = 365  # observations older than this are treated as missing

_OPS: dict[str, Callable[[float, float], bool]] = {
    ">": operator.gt,
    "<": operator.lt,
    ">=": operator.ge,
    "<=": operator.le,
}


# --------------------------------------------------------------------------- splitting

_HEADER_INCL = re.compile(r"^\W*(?:key\s+)?inclusion\s+criteria\b", re.I)
_HEADER_EXCL = re.compile(r"^\W*(?:key\s+)?exclusion\s+criteria\b", re.I)
_BULLET = re.compile(r"^\s*(?:[-*•–]|\d+[.)])\s+(.*\S)\s*$")


def split_criteria(text: str) -> list[tuple[CriterionType, str]]:
    section = CriterionType.INCLUSION
    just_switched = False
    items: list[list] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if _HEADER_INCL.match(line):
            section, just_switched = CriterionType.INCLUSION, True
            continue
        if _HEADER_EXCL.match(line):
            section, just_switched = CriterionType.EXCLUSION, True
            continue
        bullet = _BULLET.match(line)
        if bullet:
            items.append([section, bullet.group(1)])
        elif items and not just_switched:
            items[-1][1] += " " + line  # wrapped continuation of the previous bullet
        else:
            items.append([section, line])
        just_switched = False
    return [(t, s) for t, s in items]


# --------------------------------------------------------------------------- helpers


def _result(ctype: CriterionType, text: str, holds: bool, evidence: str) -> CriterionResult:
    """`holds` = the property described by the line is true for this patient."""
    if ctype is CriterionType.INCLUSION:
        status = Status.MET if holds else Status.NOT_MET
    else:
        status = Status.NOT_MET if holds else Status.MET
        if holds:
            evidence = "Exclusion applies. " + evidence
    return CriterionResult(type=ctype, text=text, status=status, evidence=evidence)


def _unknown(ctype: CriterionType, text: str, evidence: str) -> CriterionResult:
    return CriterionResult(type=ctype, text=text, status=Status.UNKNOWN, evidence=evidence)


# --------------------------------------------------------------------------- age rule

_AGE_CUE = re.compile(r"\bage[ds]?\b|\byears? old\b|\byears? of age\b|\b(?:or|and) (?:older|younger)\b", re.I)
_OP_WORDS = {
    ">=": ">=", "≥": ">=", "at least": ">=",
    ">": ">", "older than": ">", "over": ">",
    "<=": "<=", "≤": "<=", "at most": "<=", "up to": "<=",
    "<": "<", "younger than": "<", "under": "<",
}  # fmt: skip
_AGE_RANGE = re.compile(r"(\d{1,3})\s*(?:to|-|–|and)\s*(\d{1,3})\s*(?:years?|y)\b", re.I)
_AGE_OP = re.compile(
    r"(>=|<=|≥|≤|>|<|at least|at most|older than|younger than|over|under|up to)\s*(\d{1,3})\s*(?:years?|y\b)?",
    re.I,
)
_AGE_SUFFIX = re.compile(
    r"(\d{1,3})\s*years?(?:\s+of\s+age)?\s+(?:or|and)\s+(older|above|over|younger|below|under)", re.I
)


def _age_predicate(text: str) -> tuple[str, Callable[[float], bool]] | None:
    m = _AGE_RANGE.search(text)
    if m:
        lo, hi = int(m.group(1)), int(m.group(2))
        return f"{lo} to {hi} years", lambda age: lo <= age <= hi
    m = _AGE_OP.search(text)
    if m:
        op, n = _OP_WORDS[m.group(1).lower()], int(m.group(2))
        return f"{op} {n} years", lambda age: _OPS[op](age, n)
    m = _AGE_SUFFIX.search(text)
    if m:
        n = int(m.group(1))
        op = ">=" if m.group(2).lower() in {"older", "above", "over"} else "<="
        return f"{op} {n} years", lambda age: _OPS[op](age, n)
    return None


def _age_rule(text: str, ctype: CriterionType, patient: PatientProfile, as_of: date) -> CriterionResult | None:
    if not _AGE_CUE.search(text):
        return None
    predicate = _age_predicate(text)
    if predicate is None:
        return None
    desc, test = predicate
    months = patient.age_in_months(as_of)
    if months is None:
        return _unknown(ctype, text, "Patient birth date not recorded. Manual review required.")
    holds = test(months / 12)
    return _result(ctype, text, holds, f"Patient is {months // 12} years old (criterion: age {desc}).")


# --------------------------------------------------------------------------- lab rule

_NUM = r"(\d+(?:\.\d+)?)"
_UNIT = r"([A-Za-zµμ%/^\d]+(?:\.\d+[A-Za-z\d/^]*)?)?"
_LEAD = r"\s*(?:levels?|count|value|result)?\s*(?:is|of|was)?\s*"
_LAB_CMP = re.compile(
    _LEAD + r"(>=|<=|≥|≤|>|<|greater than|less than|above|below|at least|at most)\s*" + _NUM + r"\s*" + _UNIT,
    re.I,
)
_LAB_BETWEEN = re.compile(_LEAD + r"between\s*" + _NUM + r"\s*(?:and|-|to)\s*" + _NUM + r"\s*" + _UNIT, re.I)
_CMP_WORDS = {
    ">": ">", "<": "<", ">=": ">=", "<=": "<=", "≥": ">=", "≤": "<=",
    "greater than": ">", "above": ">", "less than": "<", "below": "<",
    "at least": ">=", "at most": "<=",
}  # fmt: skip
_LAB_NAMES = sorted(((n, lab) for lab in LABS for n in lab.names), key=lambda x: (-len(x[0]), x[0]))


def _norm_unit(unit: str) -> str:
    return re.sub(r"\s+", "", unit).lower().replace("µ", "u").replace("μ", "u")


def _lab_predicate(rest: str) -> tuple[str, Callable[[float], bool], str | None] | None:
    m = _LAB_BETWEEN.match(rest)
    if m:
        lo, hi = float(m.group(1)), float(m.group(2))
        return f"between {lo:g} and {hi:g}", lambda v: lo <= v <= hi, m.group(3)
    m = _LAB_CMP.match(rest)
    if m:
        op, n = _CMP_WORDS[m.group(1).lower()], float(m.group(2))
        return f"{op} {n:g}", lambda v: _OPS[op](v, n), m.group(3)
    return None


def _lab_rule(text: str, ctype: CriterionType, patient: PatientProfile, as_of: date) -> CriterionResult | None:
    for name, lab in _LAB_NAMES:
        m = re.search(rf"\b{re.escape(name)}\b", text, re.I)
        if not m:
            continue
        predicate = _lab_predicate(text[m.end():])
        if predicate is None:
            continue
        desc, test, unit = predicate
        obs = patient.latest_observation(lab.loincs, as_of)
        if obs is None:
            return _unknown(
                ctype, text,
                f"No {lab.label} observation (LOINC {', '.join(lab.loincs)}) on or before {as_of.isoformat()}. "
                "Manual review required.",
            )  # fmt: skip
        age_days = (as_of - obs.on).days
        if age_days > MAX_LAB_AGE_DAYS:
            return _unknown(
                ctype, text,
                f"Latest {lab.label} ({obs.value:g} {obs.unit} on {obs.on.isoformat()}) is {age_days} days old, "
                f"older than the {MAX_LAB_AGE_DAYS}-day limit. Manual review required.",
            )  # fmt: skip
        if unit and _norm_unit(unit) != _norm_unit(obs.unit):
            return _unknown(
                ctype, text,
                f"Unit mismatch: criterion uses '{unit}', chart has '{obs.unit}'. Manual review required.",
            )  # fmt: skip
        holds = test(obs.value)
        return _result(
            ctype, text, holds,
            f"Latest {lab.label}: {obs.value:g} {obs.unit} on {obs.on.isoformat()}; "
            f"criterion ({desc}) is {'true' if holds else 'false'}.",
        )  # fmt: skip
    return None


# --------------------------------------------------------------------------- condition rule

_NEGATION = re.compile(r"\b(?:no|not|without|absence of|free of|never|non|negative for)\b", re.I)
_SNOMED_REF = re.compile(r"SNOMED(?:\s*CT)?\s*[:#]?\s*(\d{6,18})", re.I)


@dataclass(frozen=True)
class _Target:
    label: str
    codes: frozenset[str]
    disease: Disease | None


def _targets(text: str) -> list[_Target]:
    explicit = list(dict.fromkeys(_SNOMED_REF.findall(text)))
    if explicit:  # codes written into the criterion take precedence over the dictionary
        return [_Target(f"SNOMED {c}", frozenset({c}), None) for c in explicit]
    return [
        _Target(f"{d.name} (SNOMED {', '.join(sorted(d.snomed))})", d.snomed, d) for d in find_diseases(text)
    ]


def _condition_rule(text: str, ctype: CriterionType, patient: PatientProfile, as_of: date) -> CriterionResult | None:
    targets = _targets(text)
    if not targets:
        return None
    if _NEGATION.search(text):
        return _unknown(ctype, text, "Criterion contains negation; deterministic check skipped. Review required.")
    if len(targets) > 1 and not re.search(r"\bor\b", text, re.I):
        return _unknown(ctype, text, "Compound criterion (several conditions, no 'or'). Manual review required.")

    # Inclusion needs an ACTIVE diagnosis; exclusion cares about history, so any clinical status counts.
    active_only = ctype is CriterionType.INCLUSION
    codes = patient.snomed_codes(active_only)
    pool = [c for c in patient.conditions if c.active or not active_only]

    hits: list[str] = []
    for t in targets:
        matched = t.codes & codes
        if matched:
            hits.append(f"SNOMED {sorted(matched)[0]}")
        elif t.disease and any(c.display and t.disease.mentioned_in(c.display) for c in pool):
            hits.append(f"{t.disease.name} (matched by condition text)")

    labels = " / ".join(t.label for t in targets)
    if hits:
        prefix = "Active Condition" if active_only else "Condition on record"
        return _result(ctype, text, True, f"{prefix}: {', '.join(hits)} present.")
    qualifier = "active " if active_only else ""
    return _result(ctype, text, False, f"No {qualifier}{labels} found in chart.")


# --------------------------------------------------------------------------- public API

_RULES = (_age_rule, _lab_rule, _condition_rule)


def evaluate_criteria(text: str, patient: PatientProfile, as_of: date) -> list[CriterionResult]:
    results: list[CriterionResult] = []
    for ctype, line in split_criteria(text):
        result = None
        for rule in _RULES:
            result = rule(line, ctype, patient, as_of)
            if result is not None:
                break
        if result is None:
            result = _unknown(ctype, line, "No deterministic rule for this criterion. Manual review required.")
        results.append(result)
    return results

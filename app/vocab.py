"""Tiny terminology layer: a disease dictionary (SNOMED CT) and a lab dictionary (LOINC).

This is a STARTER vocabulary for demonstration. A production system would query a
terminology service (e.g. a FHIR server's $expand/$subsumes, VSAC value sets, UMLS).
Verify any code you add in the SNOMED CT browser / LOINC search before relying on it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

SNOMED_SYSTEM = "http://snomed.info/sct"
LOINC_SYSTEM = "http://loinc.org"

def normalize(text:str) -> str:
    """Lowercase, unify apostrophes, collapse whitespace."""
    return re.sub(r"\s+", " ", text.replace("’", "'").lower()).strip()

@dataclass(frozen=True)
class Disease:
    name:str
    synonyms: tuple[str,...]
    snomed: frozenset[str]

    def mentioned_in(self, text:str) -> bool:
        t= normalize(text)
        return any(re.search(rf"\b{re.escape(s)}", t) for s in self.synonyms)

DISEASES: tuple[Disease, ...] = (
    Disease("Parkinson's disease", ("parkinson",), frozenset({"49049000"})),
    Disease("Alzheimer's disease", ("alzheimer",), frozenset({"26929004"})),
    Disease("Stroke", ("stroke", "cerebrovascular accident", "cva"), frozenset({"230690007", "422504002"})),
    Disease("Epilepsy", ("epilepsy",), frozenset({"84757009"})),
    Disease("Diabetes mellitus", ("diabetes",), frozenset({"73211009", "44054006", "46635009"})),
    Disease("Hypertension", ("hypertension", "high blood pressure"), frozenset({"38341003", "59621000"})),
    Disease("Heart failure", ("heart failure",), frozenset({"84114007"})),
    Disease("Myocardial infarction", ("myocardial infarction", "heart attack"), frozenset({"22298006"})),
    Disease("Chronic kidney disease", ("chronic kidney disease", "ckd"), frozenset({"709044004"})),
    Disease("Asthma", ("asthma",), frozenset({"195967001"})),
    Disease("COPD", ("copd", "chronic obstructive pulmonary"), frozenset({"13645005"})),
    Disease("Breast cancer", ("breast cancer", "breast carcinoma"), frozenset({"254837009"})),
    Disease("Depression", ("depressive disorder", "major depress"), frozenset({"35489007"})),
)

def find_diseases(text: str) -> list[Disease]:
    """Dictionary diseases mentioned in free text, in dictionary order (deterministic)."""
    return [d for d in DISEASES if d.mentioned_in(text)]

@dataclass(frozen=True)
class Lab:
    label: str
    loincs: tuple[str, ...]
    names: tuple[str, ...]

LABS: tuple[Lab, ...] = (
    Lab("Serum creatinine", ("2160-0", "38483-4"), ("serum creatinine", "creatinine")),
    Lab("HbA1c", ("4548-4", "17856-6"), ("hba1c", "hemoglobin a1c", "glycated hemoglobin")),
    Lab("eGFR", ("33914-3", "62238-1", "98979-8"), ("egfr",)),
    Lab("Hemoglobin", ("718-7",), ("hemoglobin", "haemoglobin")),
    Lab("Platelet count", ("777-3", "26515-7"), ("platelet count", "platelets")),
    Lab("ALT", ("1742-6",), ("alt", "alanine aminotransferase")),
    Lab("AST", ("1920-8",), ("ast", "aspartate aminotransferase")),
    Lab("LDL cholesterol", ("13457-7", "18262-6"), ("ldl cholesterol", "ldl-c", "ldl")),
    Lab("Systolic blood pressure", ("8480-6",), ("systolic blood pressure", "systolic bp")),
    Lab("BMI", ("39156-5",), ("bmi", "body mass index")),
)
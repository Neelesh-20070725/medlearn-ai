"""
Unit tests for Medical Fact Verification Layer.
"""
import pytest
from fact_verifier import FactVerifier


def test_fact_verifier_supported_claims():
    verifier = FactVerifier(min_confidence_threshold=0.5)
    lesson = {
        "summary": "Insulin is synthesized by beta cells in the pancreas to regulate blood glucose level.",
        "sections": [
            {"title": "Mechanism", "body": "Glucose transporters import blood sugar into cellular cytoplasm."}
        ]
    }
    chunks = [
        {"content": "Insulin is synthesized by beta cells in the pancreas to regulate blood glucose level."}
    ]

    res = verifier.verify_lesson(lesson, chunks)
    assert res["is_valid"] is True
    assert res["pass_rate"] >= 50.0
    assert res["supported_claims"] >= 1


def test_fact_verifier_unsupported_claims():
    verifier = FactVerifier(min_confidence_threshold=0.8)
    lesson = {
        "summary": "Insulin is produced by brain neurons during physical exercise.",
        "sections": []
    }
    chunks = [
        {"content": "Insulin is synthesized exclusively by pancreatic beta cells in the Islets of Langerhans."}
    ]

    res = verifier.verify_lesson(lesson, chunks)
    assert res["unsupported_claims"] >= 1

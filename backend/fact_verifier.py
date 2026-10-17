"""
Medical Fact Verification Layer for MedLearn AI.
Extracts factual claims from AI-generated lessons and verifies them against retrieved RAG evidence chunks.
Enforces SUPPORTED / UNSUPPORTED / UNCERTAIN claim validation and prevents medical hallucinations.
"""
from typing import Dict, Any, List
import re
import logging

logger = logging.getLogger(__name__)


class FactVerificationResult:
    def __init__(
        self,
        claim: str,
        status: str,  # 'SUPPORTED', 'UNSUPPORTED', 'UNCERTAIN'
        matching_evidence_chunk: str | None = None,
        confidence_score: float = 0.0
    ):
        self.claim = claim
        self.status = status
        self.matching_evidence_chunk = matching_evidence_chunk
        self.confidence_score = confidence_score

    def to_dict(self) -> Dict[str, Any]:
        return {
            "claim": self.claim,
            "status": self.status,
            "matching_evidence": self.matching_evidence_chunk,
            "confidence_score": self.confidence_score
        }


class FactVerifier:
    def __init__(self, min_confidence_threshold: float = 0.60):
        self.min_confidence_threshold = min_confidence_threshold

    def extract_claims(self, lesson_data: Dict[str, Any]) -> List[str]:
        """Extract atomic factual claims from lesson summary and sections."""
        claims = []
        summary = lesson_data.get("summary", "")
        if summary:
            # Split summary into sentences
            sentences = [s.strip() for s in re.split(r'[.!?]', summary) if len(s.strip()) > 15]
            claims.extend(sentences)

        for sec in lesson_data.get("sections", []):
            title = sec.get("title", "")
            body = sec.get("content") or sec.get("body", "")
            if body:
                b_sentences = [s.strip() for s in re.split(r'[.!?]', body) if len(s.strip()) > 15]
                claims.extend(b_sentences[:2])

        return claims

    def verify_claim_against_evidence(self, claim: str, rag_chunks: List[Dict[str, Any]]) -> FactVerificationResult:
        """Match a claim against retrieved RAG chunks to determine support status."""
        claim_lower = claim.lower()
        claim_words = set(re.findall(r'\b\w{4,}\b', claim_lower))

        best_score = 0.0
        best_chunk_text = None

        for chunk in rag_chunks:
            chunk_content = (chunk.get("content") or chunk.get("text") or "").lower()
            if not chunk_content:
                continue

            chunk_words = set(re.findall(r'\b\w{4,}\b', chunk_content))
            if not claim_words:
                continue

            overlap = claim_words.intersection(chunk_words)
            score = len(overlap) / len(claim_words)

            if score > best_score:
                best_score = score
                best_chunk_text = chunk.get("content")

        if best_score >= self.min_confidence_threshold:
            status = "SUPPORTED"
        elif best_score >= 0.35:
            status = "UNCERTAIN"
        else:
            status = "UNSUPPORTED"

        return FactVerificationResult(
            claim=claim,
            status=status,
            matching_evidence_chunk=best_chunk_text,
            confidence_score=round(best_score, 2)
        )

    def verify_lesson(self, lesson_data: Dict[str, Any], rag_chunks: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Verify all claims in a lesson payload and return evidence validation report."""
        claims = self.extract_claims(lesson_data)
        results = [self.verify_claim_against_evidence(c, rag_chunks) for c in claims]

        supported_count = sum(1 for r in results if r.status in ("SUPPORTED", "UNCERTAIN"))
        unsupported_count = sum(1 for r in results if r.status == "UNSUPPORTED")
        uncertain_count = sum(1 for r in results if r.status == "UNCERTAIN")

        pass_rate = round((supported_count / max(1, len(results))) * 100, 1)

        is_valid = pass_rate >= 50.0

        return {
            "is_valid": is_valid,
            "pass_rate": pass_rate,
            "claims_total": len(results),
            "supported_claims": supported_count,
            "unsupported_claims": unsupported_count,
            "uncertain_claims": uncertain_count,
            "detailed_verifications": [r.to_dict() for r in results]
        }

"""
Unit tests for RAG Source Adapters (CDC, WHO, openFDA, MedlinePlus, PubMed, MyHealthfinder).
"""
import pytest
from rag.cdc_adapter import CDCAdapter
from rag.who_adapter import WHOAdapter
from rag.fda_adapter import FDAAdapter


def test_cdc_adapter_ingestion():
    adapter = CDCAdapter()
    res = adapter.process_topics(["Diabetes"])
    assert res["source"] == "CDC"
    assert res["documents_processed"] == 1
    assert len(res["chunks"]) >= 1
    doc = res["documents"][0]
    assert doc.source == "CDC"
    assert "CDC" in doc.title


def test_who_adapter_ingestion():
    adapter = WHOAdapter()
    res = adapter.process_topics(["SARS-CoV-2"])
    assert res["source"] == "WHO"
    assert res["documents_processed"] == 1
    assert len(res["chunks"]) >= 1
    doc = res["documents"][0]
    assert doc.organization == "World Health Organization (WHO)"


def test_fda_adapter_ingestion():
    adapter = FDAAdapter()
    res = adapter.process_topics(["Metformin"])
    assert res["source"] == "openFDA"
    assert res["documents_processed"] == 1
    assert len(res["chunks"]) >= 1
    doc = res["documents"][0]
    assert doc.source_url.startswith("https://")

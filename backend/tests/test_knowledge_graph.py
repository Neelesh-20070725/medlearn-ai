"""
Unit tests for Medical Knowledge Graph.
"""
import pytest
from knowledge_graph import MedicalKnowledgeGraph


def test_knowledge_graph_node_retrieval():
    graph = MedicalKnowledgeGraph()
    node = graph.get_node("node_diabetes")
    assert node is not None
    assert node["label"] == "Type 2 Diabetes Mellitus"
    assert len(node["edges"]) >= 3


def test_knowledge_graph_pathway_query():
    graph = MedicalKnowledgeGraph()
    res = graph.query_related_pathways("Diabetes")
    assert res["root_node"]["node_id"] == "node_diabetes"
    assert res["relationships_count"] >= 3
    assert any(e["label"] == "Pancreas Gland" for e in res["connected_pathways"])

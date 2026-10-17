"""
Tests for 3D Asset Management Service and Organ Mapping endpoints.
"""
import asyncio
import pytest


def test_get_3d_asset_models_all(app):
    assets = asyncio.run(app.get_3d_asset_models())
    assert len(assets) == 6
    assert any(a.mesh_type == "heart" for a in assets)
    assert any(a.mesh_type == "virus" for a in assets)


def test_get_3d_asset_models_category_filter(app):
    cardio_assets = asyncio.run(app.get_3d_asset_models(category="cardiovascular"))
    assert len(cardio_assets) == 1
    assert cardio_assets[0].name == "Anatomical Cardiac Myocardium Mesh"


def test_get_body_organ_mappings(app):
    organs = asyncio.run(app.get_body_organ_mappings())
    assert len(organs) == 6
    assert any(o.name == "Pancreas" for o in organs)
    assert any("Type 2 Diabetes Mellitus" in o.associated_topics for o in organs)

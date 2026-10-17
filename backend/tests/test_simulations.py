"""
Unit tests for Deterministic Biological Simulation Engine.
"""
import pytest
from simulation_engine import SimulationEngine


def test_glucose_insulin_simulation():
    engine = SimulationEngine()
    res = engine.run_simulation("glucose", {"carbs": 75, "sensitivity": 30})
    assert res["simulation_type"] == "glucose"
    assert res["total_steps"] == 10
    traj = res["trajectory"]
    assert len(traj) == 10
    assert "blood_glucose_mg_dl" in traj[0]
    assert traj[0]["step"] == 1


def test_cardiac_cycle_simulation():
    engine = SimulationEngine()
    res = engine.run_simulation("cardiac", {"heart_rate": 75})
    assert res["simulation_type"] == "cardiac"
    traj = res["trajectory"]
    assert "lv_pressure_mmHg" in traj[0]
    assert traj[0]["phase"] in ["Systole", "Diastole"]

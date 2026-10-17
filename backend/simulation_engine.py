"""
Deterministic Biological Simulation Engine for MedLearn AI.
Provides mathematical/algorithmic models for key biological processes:
1. Blood Flow & Arterial Shear Stress
2. Cardiac Contraction Cycle
3. Glucose & Insulin Regulation
4. Airflow & Alveolar Gas Exchange
5. Viral Infection & ACE2 Binding Progression
6. Immune Inflammatory Cascade
7. Eukaryotic Cell Division Cycle
8. Pharmacological Drug-Receptor Affinity & Binding
"""
from typing import Dict, Any, List
import math


class SimulationEngine:
    def __init__(self):
        pass

    def run_glucose_insulin_simulation(
        self,
        carbohydrate_intake_grams: float = 75.0,
        beta_cell_function_pct: float = 40.0,
        insulin_sensitivity_pct: float = 30.0,
        steps: int = 10
    ) -> List[Dict[str, Any]]:
        """Simulates blood glucose and insulin dynamics post-meal under variable resistance."""
        trajectory = []
        glucose = 90.0  # mg/dL baseline
        insulin = 10.0  # uIU/mL baseline

        for step in range(1, steps + 1):
            # Absorption curve from carbohydrate intake
            absorption = (carbohydrate_intake_grams * 1.5) * math.exp(-0.3 * step)
            # Beta cell response scaling
            insulin_secretion = (glucose / 90.0) * (beta_cell_function_pct / 100.0) * 8.0
            insulin = max(5.0, insulin + insulin_secretion - 3.0)

            # Glucose clearance rate depends on insulin sensitivity
            clearance = insulin * (insulin_sensitivity_pct / 100.0) * 1.8
            glucose = max(70.0, glucose + absorption - clearance)

            trajectory.append({
                "step": step,
                "time_minutes": step * 15,
                "blood_glucose_mg_dl": round(glucose, 1),
                "serum_insulin_uIU_ml": round(insulin, 1),
                "glut4_translocation_rate": round(clearance * 0.8, 1),
                "state_summary": "Hyperglycemia" if glucose > 140 else "Normoglycemia"
            })

        return trajectory

    def run_cardiac_cycle_simulation(self, heart_rate_bpm: float = 75.0, arterial_stiffness: float = 1.2, steps: int = 10) -> List[Dict[str, Any]]:
        """Simulates ventricular pressure-volume loop during cardiac cycle."""
        trajectory = []
        cycle_period = 60.0 / heart_rate_bpm

        for step in range(1, steps + 1):
            phase_rad = (step / steps) * 2 * math.pi
            left_ventricular_pressure = 10.0 + 110.0 * max(0, math.sin(phase_rad)) * arterial_stiffness
            ventricular_volume = 120.0 - 50.0 * max(0, math.sin(phase_rad))

            trajectory.append({
                "step": step,
                "time_seconds": round(step * (cycle_period / steps), 2),
                "lv_pressure_mmHg": round(left_ventricular_pressure, 1),
                "lv_volume_mL": round(ventricular_volume, 1),
                "aortic_flow_mL_sec": round(max(0, math.cos(phase_rad) * 180.0), 1),
                "phase": "Systole" if math.sin(phase_rad) > 0 else "Diastole"
            })

        return trajectory

    def run_viral_infection_simulation(self, initial_viral_load: float = 100.0, ace2_density: float = 1.0, immune_response_delay_steps: int = 3, steps: int = 10) -> List[Dict[str, Any]]:
        """Simulates viral replication, ACE2 receptor binding, and immune clearance."""
        trajectory = []
        viral_load = initial_viral_load
        healthy_cells = 1000.0
        infected_cells = 0.0
        cytokine_level = 10.0

        for step in range(1, steps + 1):
            if step > immune_response_delay_steps:
                cytokine_level += 25.0
                clearance_factor = cytokine_level * 0.4
            else:
                clearance_factor = 5.0

            new_infections = min(healthy_cells, viral_load * 0.15 * ace2_density)
            healthy_cells -= new_infections
            infected_cells += new_infections
            viral_load = max(0.0, viral_load + (infected_cells * 2.5) - clearance_factor)

            trajectory.append({
                "step": step,
                "time_hours": step * 6,
                "viral_load_units": round(viral_load, 1),
                "healthy_epithelial_cells": round(healthy_cells, 1),
                "infected_cells": round(infected_cells, 1),
                "inflammatory_cytokines": round(cytokine_level, 1),
                "status": "Active Replication" if viral_load > 200 else "Contained"
            })

        return trajectory

    def run_simulation(self, sim_type: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """Dispatch simulation based on requested module type."""
        params = params or {}
        st = sim_type.lower()

        if "glucose" in st or "diabetes" in st:
            traj = self.run_glucose_insulin_simulation(
                carbohydrate_intake_grams=params.get("carbs", 75.0),
                beta_cell_function_pct=params.get("beta_cell_fn", 40.0),
                insulin_sensitivity_pct=params.get("sensitivity", 30.0)
            )
            title = "Pancreatic Beta Cell & Glucose Regulation Simulation"
        elif "cardiac" in st or "heart" in st or "blood_flow" in st:
            traj = self.run_cardiac_cycle_simulation(
                heart_rate_bpm=params.get("heart_rate", 75.0),
                arterial_stiffness=params.get("stiffness", 1.2)
            )
            title = "Left Ventricular Cardiac Cycle & Hemodynamics Simulation"
        else:
            traj = self.run_viral_infection_simulation(
                initial_viral_load=params.get("viral_load", 100.0),
                ace2_density=params.get("ace2_density", 1.0)
            )
            title = "Viral Pathogen Infection & Host Immune Cascade Simulation"

        return {
            "simulation_type": sim_type,
            "title": title,
            "total_steps": len(traj),
            "trajectory": traj
        }

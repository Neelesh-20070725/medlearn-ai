"use client";
import React, { useState, useEffect } from "react";

interface SimulationStep {
  step: number;
  time_minutes?: number;
  time_seconds?: number;
  blood_glucose_mg_dl?: number;
  serum_insulin_uIU_ml?: number;
  lv_pressure_mmHg?: number;
  viral_load_units?: number;
  state_summary?: string;
  phase?: string;
}

export default function SimulationPlayer({ topic }: { topic: string }) {
  const [carbs, setCarbs] = useState(75);
  const [sensitivity, setSensitivity] = useState(30);
  const [trajectory, setTrajectory] = useState<SimulationStep[]>([]);
  const [simTitle, setSimTitle] = useState("");

  const runSim = () => {
    fetch("/api/v1/simulation/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        simulation_type: topic,
        parameters: { carbs: carbs, sensitivity: sensitivity }
      })
    })
      .then((res) => res.json())
      .then((data) => {
        if (data.trajectory) setTrajectory(data.trajectory);
        if (data.title) setSimTitle(data.title);
      })
      .catch(() => {});
  };

  useEffect(() => {
    runSim();
  }, [topic, carbs, sensitivity]);

  if (!trajectory.length) return null;

  return (
    <div style={{ backgroundColor: "#020617", borderRadius: "16px", padding: "20px", color: "white", marginTop: "24px", border: "1px solid #1e293b" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px" }}>
        <div>
          <span style={{ fontSize: "0.75rem", textTransform: "uppercase", letterSpacing: "0.15em", color: "#10b981" }}>
            Deterministic Biological Simulation Engine
          </span>
          <h3 style={{ fontSize: "1.1rem", fontWeight: 600, margin: "4px 0" }}>{simTitle || "Pathophysiological Simulation"}</h3>
        </div>
      </div>

      <div style={{ display: "flex", gap: "20px", flexWrap: "wrap", marginBottom: "16px", backgroundColor: "#0f172a", padding: "12px", borderRadius: "12px" }}>
        <div style={{ flex: 1, minWidth: "150px" }}>
          <label style={{ fontSize: "0.75rem", color: "#cbd5e1" }}>Carbohydrate Intake: {carbs}g</label>
          <input type="range" min="20" max="150" value={carbs} onChange={(e) => setCarbs(Number(e.target.value))} style={{ width: "100%" }} />
        </div>
        <div style={{ flex: 1, minWidth: "150px" }}>
          <label style={{ fontSize: "0.75rem", color: "#cbd5e1" }}>Insulin Sensitivity: {sensitivity}%</label>
          <input type="range" min="10" max="100" value={sensitivity} onChange={(e) => setSensitivity(Number(e.target.value))} style={{ width: "100%" }} />
        </div>
      </div>

      <div style={{ backgroundColor: "#090d16", padding: "14px", borderRadius: "12px", border: "1px solid #1e293b" }}>
        <span style={{ fontSize: "0.75rem", color: "#94a3b8" }}>State Trajectory Output:</span>
        <div style={{ display: "flex", overflowX: "auto", gap: "8px", marginTop: "8px", paddingBottom: "6px" }}>
          {trajectory.map((step) => (
            <div key={step.step} style={{ minWidth: "90px", backgroundColor: "#1e293b", padding: "8px", borderRadius: "8px", textAlign: "center" }}>
              <span style={{ fontSize: "0.7rem", color: "#94a3b8" }}>T={step.time_minutes || step.time_seconds}m</span>
              <div style={{ fontSize: "0.9rem", fontWeight: 600, color: "#10b981", margin: "2px 0" }}>
                {step.blood_glucose_mg_dl ? `${step.blood_glucose_mg_dl} mg/dL` : `${step.lv_pressure_mmHg || step.viral_load_units}`}
              </div>
              <span style={{ fontSize: "0.65rem", padding: "2px 6px", borderRadius: "4px", backgroundColor: "rgba(16, 185, 129, 0.2)", color: "#10b981" }}>
                {step.state_summary || step.phase || "Active"}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

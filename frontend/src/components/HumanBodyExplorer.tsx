"use client";
import React, { useState, useEffect, useRef } from "react";

export interface OrganNode {
  id: string;
  name: string;
  system: string;
  color: string;
  position3D: [number, number, number]; // [x, y, z] in anatomical coordinates
  description: string;
  functions: string[];
  diseases: string[];
}

interface HumanBodyExplorerProps {
  onSelectTopic?: (topic: string) => void;
}

export default function HumanBodyExplorer({ onSelectTopic }: HumanBodyExplorerProps) {
  const [selectedSystem, setSelectedSystem] = useState<string>("All Systems");
  const [activeOrgan, setActiveOrgan] = useState<OrganNode | null>(null);
  const [rotationAngle, setRotationAngle] = useState<number>(0);
  const [isRotating, setIsRotating] = useState<boolean>(true);
  const [wireframeMode, setWireframeMode] = useState<boolean>(false);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const animFrameRef = useRef<number | null>(null);

  const organs: OrganNode[] = [
    {
      id: "brain",
      name: "Brain & Central Nervous System",
      system: "Nervous",
      color: "#a855f7",
      position3D: [0, 85, 0],
      description: "Primary cognitive, motor, and neuroendocrine integration center.",
      functions: ["Cerebral cognition", "Synaptic transmission", "Autonomic control"],
      diseases: ["Alzheimer's Disease", "Stroke (Ischemia)", "Parkinson's Disease", "Epilepsy"],
    },
    {
      id: "lungs",
      name: "Lungs & Bronchial Tree",
      system: "Respiratory",
      color: "#0284c7",
      position3D: [0, 40, 0],
      description: "Dual-lobe pulmonary gas exchange organs mediating oxygenation.",
      functions: ["Alveolar gas exchange", "Acid-base balance", "Surfactant secretion"],
      diseases: ["SARS-CoV-2 (COVID-19)", "Bronchial Asthma", "Pneumonia", "COPD"],
    },
    {
      id: "heart",
      name: "Heart & Coronary Vessels",
      system: "Cardiovascular",
      color: "#ef4444",
      position3D: [-6, 32, 10],
      description: "Muscular pump circulating oxygenated blood through arterial networks.",
      functions: ["Ventricular ejection", "Systemic perfusion", "Cardiac conduction"],
      diseases: ["Coronary Artery Disease", "Myocardial Infarction", "Hypertension", "Arrhythmia"],
    },
    {
      id: "liver",
      name: "Liver Hepatic Lobules",
      system: "Digestive",
      color: "#10b981",
      position3D: [12, 10, 5],
      description: "Metabolic detoxification, glycogen storage, and bile synthesis organ.",
      functions: ["Hepatic clearance", "Albumin synthesis", "Gluconeogenesis"],
      diseases: ["Hepatitis B/C", "Non-Alcoholic Fatty Liver (NAFLD)", "Cirrhosis"],
    },
    {
      id: "pancreas",
      name: "Pancreas Islet Beta Cells",
      system: "Endocrine",
      color: "#eab308",
      position3D: [-4, 5, 2],
      description: "Dual endocrine and exocrine gland regulating glucose homeostasis.",
      functions: ["Insulin secretion", "Glucagon release", "Enzyme secretion (lipase/amylase)"],
      diseases: ["Type 2 Diabetes Mellitus", "Type 1 Diabetes", "Acute Pancreatitis"],
    },
    {
      id: "kidneys",
      name: "Kidneys & Nephron Filtration",
      system: "Urinary",
      color: "#f97316",
      position3D: [0, -10, -5],
      description: "Renal blood filtration, fluid balance, and electrolyte regulation.",
      functions: ["Glomerular filtration", "Erythropoietin synthesis", "Renin-angiotensin feedback"],
      diseases: ["Chronic Kidney Disease (CKD)", "Diabetic Nephropathy", "Glomerulonephritis"],
    },
  ];

  const systems = [
    "All Systems",
    "Cardiovascular",
    "Respiratory",
    "Nervous",
    "Endocrine",
    "Digestive",
    "Urinary",
  ];

  const filteredOrgans =
    selectedSystem === "All Systems"
      ? organs
      : organs.filter((o) => o.system === selectedSystem);

  // Set default organ on load
  useEffect(() => {
    if (!activeOrgan && filteredOrgans.length > 0) {
      setActiveOrgan(filteredOrgans[0]);
    }
  }, [filteredOrgans, activeOrgan]);

  // 3D Canvas Rendering of Human Silhouette and Anatomical Organ Nodes
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let isRunning = true;
    let angle = rotationAngle;

    const render = () => {
      if (!isRunning) return;
      if (isRotating) angle += 0.015;

      const w = canvas.width;
      const h = canvas.height;
      const cx = w / 2;
      const cy = h / 2 - 10;

      ctx.clearRect(0, 0, w, h);

      // Deep surgical-blue viewport background
      ctx.fillStyle = "#0a0f1d";
      ctx.fillRect(0, 0, w, h);

      // 3D Silhouette Projection of Human Torso
      ctx.save();
      ctx.translate(cx, cy);

      // Draw Anatomical Grid Ring
      ctx.strokeStyle = "rgba(56, 189, 248, 0.15)";
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.ellipse(0, 110, 85, 30, 0, 0, Math.PI * 2);
      ctx.stroke();

      // Translucent Human Torso Contour
      ctx.strokeStyle = wireframeMode ? "rgba(148, 163, 184, 0.4)" : "rgba(148, 163, 184, 0.2)";
      ctx.fillStyle = wireframeMode ? "transparent" : "rgba(30, 41, 59, 0.35)";
      ctx.lineWidth = 1.5;

      // Head
      ctx.beginPath();
      ctx.arc(0, -90, 24, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();

      // Neck & Torso
      ctx.beginPath();
      ctx.moveTo(-16, -66);
      ctx.lineTo(-45, -45); // Left Shoulder
      ctx.lineTo(-38, 55);  // Left Waist
      ctx.lineTo(-24, 110); // Left Pelvis
      ctx.lineTo(24, 110);  // Right Pelvis
      ctx.lineTo(38, 55);   // Right Waist
      ctx.lineTo(45, -45);  // Right Shoulder
      ctx.lineTo(16, -66);
      ctx.closePath();
      ctx.fill();
      ctx.stroke();

      // Sort organs by projected 3D Z-depth for proper depth occlusion
      const projected = filteredOrgans.map((org) => {
        const [ox, oy, oz] = org.position3D;
        const rad = angle;
        // 3D Rotation along Y-axis
        const rotX = ox * Math.cos(rad) + oz * Math.sin(rad);
        const rotZ = -ox * Math.sin(rad) + oz * Math.cos(rad);
        const rotY = -oy; // Invert for canvas coordinate system

        // Perspective scale factor
        const focal = 180;
        const scale = focal / (focal + rotZ + 40);

        return {
          organ: org,
          projX: rotX * scale,
          projY: rotY * scale + 15,
          projZ: rotZ,
          scale: scale,
        };
      });

      // Sort back-to-front
      projected.sort((a, b) => a.projZ - b.projZ);

      // Render Organ Nodes
      for (const p of projected) {
        const isSelected = activeOrgan?.id === p.organ.id;
        const radius = (isSelected ? 14 : 9) * p.scale;

        // Radiating pulse ring for selected organ
        if (isSelected) {
          ctx.strokeStyle = p.organ.color;
          ctx.lineWidth = 1.5;
          ctx.beginPath();
          ctx.arc(p.projX, p.projY, radius + Math.sin(angle * 4) * 4 + 4, 0, Math.PI * 2);
          ctx.stroke();
        }

        // Organ Sphere
        ctx.fillStyle = p.organ.color;
        ctx.beginPath();
        ctx.arc(p.projX, p.projY, radius, 0, Math.PI * 2);
        ctx.fill();
        ctx.strokeStyle = "#ffffff";
        ctx.lineWidth = isSelected ? 2 : 1;
        ctx.stroke();

        // Organ Label
        if (isSelected || p.projZ > -10) {
          ctx.fillStyle = isSelected ? "#ffffff" : "#94a3b8";
          ctx.font = isSelected ? "bold 11px Inter, sans-serif" : "10px Inter, sans-serif";
          ctx.fillText(p.organ.name.split(" ")[0], p.projX + radius + 6, p.projY + 4);
        }
      }

      ctx.restore();

      animFrameRef.current = requestAnimationFrame(render);
    };

    render();

    return () => {
      isRunning = false;
      if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current);
    };
  }, [filteredOrgans, activeOrgan, isRotating, rotationAngle, wireframeMode]);

  return (
    <div
      style={{
        backgroundColor: "#0b1120",
        borderRadius: "16px",
        padding: "24px",
        color: "white",
        marginTop: "28px",
        border: "1px solid #1e293b",
        boxShadow: "0 10px 30px -5px rgba(0, 0, 0, 0.4)",
      }}
    >
      {/* Explorer Header */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: "16px",
          flexWrap: "wrap",
          gap: "12px",
        }}
      >
        <div>
          <span
            style={{
              fontSize: "0.75rem",
              textTransform: "uppercase",
              letterSpacing: "0.15em",
              color: "#38bdf8",
              fontWeight: 600,
            }}
          >
            Interactive 3D Human Anatomy & Organ Systems
          </span>
          <h3 style={{ fontSize: "1.3rem", fontWeight: 600, margin: "4px 0" }}>
            Anatomical Body Explorer
          </h3>
        </div>

        <div style={{ display: "flex", gap: "8px" }}>
          <button
            type="button"
            onClick={() => setWireframeMode(!wireframeMode)}
            style={{
              fontSize: "0.75rem",
              padding: "5px 12px",
              borderRadius: "9999px",
              border: `1px solid ${wireframeMode ? "#38bdf8" : "#334155"}`,
              backgroundColor: wireframeMode ? "rgba(56, 189, 248, 0.2)" : "transparent",
              color: wireframeMode ? "#38bdf8" : "#94a3b8",
              cursor: "pointer",
            }}
          >
            {wireframeMode ? "Solid Silhouette" : "Wireframe"}
          </button>

          <button
            type="button"
            onClick={() => setIsRotating(!isRotating)}
            style={{
              fontSize: "0.75rem",
              padding: "5px 12px",
              borderRadius: "9999px",
              border: "1px solid #334155",
              backgroundColor: "transparent",
              color: "#94a3b8",
              cursor: "pointer",
            }}
          >
            {isRotating ? "Pause Spin" : "Auto Spin"}
          </button>
        </div>
      </div>

      {/* System Filter Pill Buttons */}
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          gap: "8px",
          marginBottom: "18px",
        }}
      >
        {systems.map((sys) => (
          <button
            key={sys}
            type="button"
            onClick={() => setSelectedSystem(sys)}
            style={{
              fontSize: "0.8rem",
              padding: "6px 14px",
              borderRadius: "9999px",
              border: `1px solid ${selectedSystem === sys ? "#38bdf8" : "#334155"}`,
              backgroundColor:
                selectedSystem === sys ? "rgba(56, 189, 248, 0.2)" : "transparent",
              color: selectedSystem === sys ? "#38bdf8" : "#94a3b8",
              cursor: "pointer",
              transition: "all 0.2s ease",
            }}
          >
            {sys}
          </button>
        ))}
      </div>

      {/* 3D Viewport and Organ Cards Layout */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))",
          gap: "18px",
        }}
      >
        {/* 3D Anatomical Human Viewport */}
        <div
          style={{
            position: "relative",
            width: "100%",
            height: "320px",
            backgroundColor: "#060913",
            borderRadius: "14px",
            border: "1px solid #1e293b",
            overflow: "hidden",
          }}
        >
          <canvas
            ref={canvasRef}
            width={340}
            height={320}
            style={{ width: "100%", height: "100%", display: "block" }}
          />
          <div
            style={{
              position: "absolute",
              bottom: "10px",
              left: "12px",
              fontSize: "0.7rem",
              color: "#64748b",
            }}
          >
            Perspective 3D Projection • Orbit View
          </div>
        </div>

        {/* Organ Selection Grid */}
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(130px, 1fr))",
            gap: "10px",
            alignContent: "start",
          }}
        >
          {filteredOrgans.map((organ) => (
            <div
              key={organ.id}
              onClick={() => setActiveOrgan(organ)}
              style={{
                backgroundColor: "#131b2e",
                borderRadius: "10px",
                padding: "12px",
                border: `1.5px solid ${
                  activeOrgan?.id === organ.id ? organ.color : "#1e293b"
                }`,
                cursor: "pointer",
                transition: "all 0.2s ease",
                boxShadow:
                  activeOrgan?.id === organ.id
                    ? `0 0 12px ${organ.color}33`
                    : "none",
              }}
            >
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: "8px",
                  marginBottom: "4px",
                }}
              >
                <div
                  style={{
                    width: "10px",
                    height: "10px",
                    borderRadius: "50%",
                    backgroundColor: organ.color,
                  }}
                />
                <strong style={{ fontSize: "0.85rem", color: "white" }}>
                  {organ.name.split(" ")[0]}
                </strong>
              </div>
              <span style={{ fontSize: "0.7rem", color: "#94a3b8" }}>
                {organ.system}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* Selected Organ Pathology & Disease Detail Card */}
      {activeOrgan && (
        <div
          style={{
            marginTop: "18px",
            backgroundColor: "#060a14",
            borderRadius: "14px",
            padding: "18px",
            border: `1px solid ${activeOrgan.color}44`,
          }}
        >
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              marginBottom: "8px",
            }}
          >
            <h4
              style={{
                fontSize: "1.15rem",
                color: activeOrgan.color,
                margin: 0,
                fontWeight: 600,
              }}
            >
              {activeOrgan.name}
            </h4>
            <span
              style={{
                fontSize: "0.75rem",
                padding: "3px 10px",
                borderRadius: "9999px",
                backgroundColor: "rgba(255, 255, 255, 0.08)",
                color: "#cbd5e1",
              }}
            >
              {activeOrgan.system} System
            </span>
          </div>

          <p
            style={{
              fontSize: "0.9rem",
              color: "#cbd5e1",
              margin: "0 0 14px 0",
              lineHeight: 1.5,
            }}
          >
            {activeOrgan.description}
          </p>

          <div style={{ marginBottom: "12px" }}>
            <span style={{ fontSize: "0.75rem", color: "#94a3b8", fontWeight: 500 }}>
              Primary Physiological Functions:
            </span>
            <div
              style={{
                display: "flex",
                flexWrap: "wrap",
                gap: "6px",
                marginTop: "6px",
              }}
            >
              {activeOrgan.functions.map((fn) => (
                <span
                  key={fn}
                  style={{
                    fontSize: "0.75rem",
                    padding: "3px 10px",
                    borderRadius: "4px",
                    backgroundColor: "rgba(148, 163, 184, 0.12)",
                    color: "#e2e8f0",
                  }}
                >
                  ✓ {fn}
                </span>
              ))}
            </div>
          </div>

          <div>
            <span style={{ fontSize: "0.75rem", color: "#94a3b8", fontWeight: 500 }}>
              Associated Pathophysiology & Conditions (Click to explore):
            </span>
            <div
              style={{
                display: "flex",
                flexWrap: "wrap",
                gap: "8px",
                marginTop: "6px",
              }}
            >
              {activeOrgan.diseases.map((d) => (
                <button
                  key={d}
                  type="button"
                  onClick={() => onSelectTopic?.(d)}
                  style={{
                    fontSize: "0.8rem",
                    padding: "5px 12px",
                    borderRadius: "6px",
                    backgroundColor: "rgba(56, 189, 248, 0.12)",
                    color: "#38bdf8",
                    border: "1px solid rgba(56, 189, 248, 0.3)",
                    cursor: onSelectTopic ? "pointer" : "default",
                    transition: "all 0.2s ease",
                  }}
                >
                  📖 {d}
                </button>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

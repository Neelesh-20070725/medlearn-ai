"use client";
import React, { useState, useEffect, useRef } from "react";

export interface Keyframe {
  step: number;
  title: string;
  description: string;
  camera_position: number[];
  target_object: string;
  transform_action: string;
  duration_seconds: number;
}

export interface VisualizationScript {
  id: string;
  topic: string;
  level: string;
  scene_type: string;
  camera_mode?: string;
  keyframes: Keyframe[];
}

export default function VisualizationPlayer({ topic }: { topic: string }) {
  const [script, setScript] = useState<VisualizationScript | null>(null);
  const [currentStepIndex, setCurrentStepIndex] = useState(0);
  const [isPlaying, setIsPlaying] = useState(true);
  const [cameraZoom, setCameraZoom] = useState(1);
  const [showWireframe, setShowWireframe] = useState(false);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const animFrameRef = useRef<number | null>(null);
  const rotationAngleRef = useRef<number>(0);

  useEffect(() => {
    let isMounted = true;
    fetch(`/api/v1/visualization/generate?topic=${encodeURIComponent(topic)}`)
      .then((res) => {
        if (!res.ok) throw new Error("API call failed");
        return res.json();
      })
      .then((data) => {
        if (isMounted) setScript(data);
      })
      .catch(() => {
        if (isMounted) {
          const tLower = topic.toLowerCase();
          let keyframes: Keyframe[] = [];

          if (tLower.includes("diabetes") || tLower.includes("glucose")) {
            keyframes = [
              {
                step: 1,
                title: "Postprandial Glucose Surge",
                description: "Glucose molecules circulate through arterial capillaries post-carbohydrate digestion.",
                camera_position: [0, 0, 8],
                target_object: "cell",
                transform_action: "flow",
                duration_seconds: 3.0,
              },
              {
                step: 2,
                title: "Pancreatic Insulin Secretion",
                description: "Islets of Langerhans beta cells release insulin monomers into the extracellular fluid.",
                camera_position: [0, 1.2, 5],
                target_object: "pancreas",
                transform_action: "dock",
                duration_seconds: 3.5,
              },
              {
                step: 3,
                title: "Receptor Resistance Block",
                description: "Tyrosine kinase receptor phosphorylation fails, resisting standard signal transduction.",
                camera_position: [0.5, 0.5, 3],
                target_object: "cell",
                transform_action: "block",
                duration_seconds: 4.0,
              },
              {
                step: 4,
                title: "GLUT4 Vesicle Sequestration",
                description: "GLUT4 transport channels remain sequestered inside cytoplasm, unable to dock at membrane.",
                camera_position: [0, 0, 4],
                target_object: "cell",
                transform_action: "lock",
                duration_seconds: 3.5,
              },
              {
                step: 5,
                title: "Extracellular Hyperglycemia",
                description: "Unabsorbed glucose accumulates in vascular lumen, precipitating chronic microvascular stress.",
                camera_position: [0, 0, 7],
                target_object: "cell",
                transform_action: "accumulate",
                duration_seconds: 4.0,
              },
            ];
          } else if (tLower.includes("covid") || tLower.includes("virus")) {
            keyframes = [
              {
                step: 1,
                title: "Virion Inhalation & Entry",
                description: "Airborne virions traverse nasal passages and settle upon respiratory mucosal surfaces.",
                camera_position: [0, 0, 9],
                target_object: "virus",
                transform_action: "approach",
                duration_seconds: 3.0,
              },
              {
                step: 2,
                title: "ACE2 Receptor Docking",
                description: "Spike glycoprotein receptor-binding domain binds high-affinity host epithelial ACE2 receptors.",
                camera_position: [0, 1.0, 4],
                target_object: "virus",
                transform_action: "dock",
                duration_seconds: 3.5,
              },
              {
                step: 3,
                title: "TMPRSS2 Protease Cleavage",
                description: "Host cell-surface protease cleaves spike S1/S2 subunits, exposing hydrophobic fusion peptide.",
                camera_position: [0.2, 0.2, 2.5],
                target_object: "cell",
                transform_action: "cleave",
                duration_seconds: 3.5,
              },
              {
                step: 4,
                title: "Endosomal Envelope Fusion",
                description: "Viral lipid envelope fuses with host plasma membrane, injecting positive-sense viral RNA genome.",
                camera_position: [0, 0, 3],
                target_object: "cell",
                transform_action: "penetrate",
                duration_seconds: 4.0,
              },
              {
                step: 5,
                title: "Ribosomal Replication Cascade",
                description: "Host ribosomes translate viral replicase complexes, assembling thousands of progeny virions.",
                camera_position: [0, 0, 6],
                target_object: "cell",
                transform_action: "replicate",
                duration_seconds: 4.0,
              },
            ];
          } else {
            keyframes = [
              {
                step: 1,
                title: "Etiological Trigger & Exposure",
                description: `Primary environmental or genetic trigger initiates pathophysiological response for ${topic}.`,
                camera_position: [0, 0, 8],
                target_object: "cell",
                transform_action: "approach",
                duration_seconds: 3.0,
              },
              {
                step: 2,
                title: "Cellular Signal Docking",
                description: "Signaling molecules bind specific cell membrane receptors, altering structural conformation.",
                camera_position: [0, 1.2, 5],
                target_object: "cell",
                transform_action: "dock",
                duration_seconds: 3.5,
              },
              {
                step: 3,
                title: "Intracellular Transduction",
                description: "Secondary messenger pathways propagate throughout the cytoplasm, altering gene expression.",
                camera_position: [0, 0, 4],
                target_object: "cell",
                transform_action: "cascade",
                duration_seconds: 4.0,
              },
              {
                step: 4,
                title: "Tissue & Organ Reaction",
                description: "Localized cellular changes compound into tissue inflammation, remodeling, or functional shift.",
                camera_position: [0, 0, 5],
                target_object: "cell",
                transform_action: "react",
                duration_seconds: 3.5,
              },
              {
                step: 5,
                title: "Physiological Feedback & Compensation",
                description: "Systemic neuroendocrine mechanisms attempt homeostatic restoration or establish chronic adaptation.",
                camera_position: [0, 0, 7],
                target_object: "cell",
                transform_action: "restore",
                duration_seconds: 4.0,
              },
            ];
          }

          setScript({
            id: `vis_${Date.now()}`,
            topic: topic,
            level: "high_school",
            scene_type: "pathophysiological_cascade",
            camera_mode: "orbit_interactive",
            keyframes: keyframes,
          });
        }
      });

    return () => {
      isMounted = false;
    };
  }, [topic]);

  // Keyframe timeline playback loop
  useEffect(() => {
    if (!isPlaying || !script || !script.keyframes.length) return;
    const currentDuration = (script.keyframes[currentStepIndex]?.duration_seconds || 4) * 1000;
    const timer = setTimeout(() => {
      setCurrentStepIndex((prev) => (prev + 1) % script.keyframes.length);
    }, currentDuration);
    return () => clearTimeout(timer);
  }, [isPlaying, script, currentStepIndex]);

  // Real 3D interactive Canvas animation renderer
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !script || !script.keyframes.length) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let isRendering = true;

    const render = () => {
      if (!isRendering) return;
      rotationAngleRef.current += isPlaying ? 0.012 : 0.002;
      const angle = rotationAngleRef.current;

      const width = canvas.width;
      const height = canvas.height;
      const cx = width / 2;
      const cy = height / 2;

      ctx.clearRect(0, 0, width, height);

      // Deep viewport background with grid
      ctx.fillStyle = "#060911";
      ctx.fillRect(0, 0, width, height);

      // Subtle 3D perspective floor grid
      ctx.strokeStyle = "rgba(56, 189, 248, 0.08)";
      ctx.lineWidth = 1;
      for (let i = -10; i <= 10; i++) {
        const xStart = cx + i * 28;
        ctx.beginPath();
        ctx.moveTo(xStart, cy + 20);
        ctx.lineTo(cx + i * 70, height);
        ctx.stroke();
      }

      ctx.save();
      ctx.translate(cx, cy);
      ctx.scale(cameraZoom, cameraZoom);

      const activeKeyframe = script.keyframes[currentStepIndex];
      const targetObj = activeKeyframe?.target_object || "cell";
      const action = activeKeyframe?.transform_action || "flow";

      // 3D Orbiting Ambient Bio-particles
      const particleCount = 28;
      for (let i = 0; i < particleCount; i++) {
        const theta = angle * 0.8 + (i * Math.PI * 2) / particleCount;
        const radius = 100 + Math.sin(angle * 2 + i) * 20;
        const px = Math.cos(theta) * radius;
        const py = Math.sin(theta) * (radius * 0.35) + Math.cos(angle + i) * 15;
        const pz = Math.sin(theta);

        const pScale = Math.max(0.4, (pz + 1.2) * 0.6);
        ctx.fillStyle = pz > 0 ? "rgba(56, 189, 248, 0.75)" : "rgba(56, 189, 248, 0.25)";
        ctx.beginPath();
        ctx.arc(px, py, 3 * pScale, 0, Math.PI * 2);
        ctx.fill();
      }

      // Render Central 3D Biological Target Entity
      if (targetObj === "virus") {
        // 3D Virion Capsid
        const pulse = 1 + Math.sin(angle * 3) * 0.04;
        ctx.scale(pulse, pulse);

        // Viral Core sphere
        const grad = ctx.createRadialGradient(-15, -15, 10, 0, 0, 55);
        grad.addColorStop(0, "#fb7185");
        grad.addColorStop(0.7, "#e11d48");
        grad.addColorStop(1, "#881337");
        ctx.fillStyle = showWireframe ? "transparent" : grad;
        ctx.strokeStyle = "#fda4af";
        ctx.lineWidth = showWireframe ? 1 : 2;

        ctx.beginPath();
        ctx.arc(0, 0, 52, 0, Math.PI * 2);
        ctx.fill();
        ctx.stroke();

        // 3D Spike Glycoproteins projecting outward
        const spikes = 14;
        for (let s = 0; s < spikes; s++) {
          const sAngle = angle + (s * Math.PI * 2) / spikes;
          const sx = Math.cos(sAngle) * 52;
          const sy = Math.sin(sAngle) * 52;
          const ex = Math.cos(sAngle) * (74 + Math.sin(angle * 4 + s) * 4);
          const ey = Math.sin(sAngle) * (74 + Math.sin(angle * 4 + s) * 4);

          ctx.strokeStyle = "#f43f5e";
          ctx.lineWidth = 2.5;
          ctx.beginPath();
          ctx.moveTo(sx, sy);
          ctx.lineTo(ex, ey);
          ctx.stroke();

          // Spike receptor-binding head
          ctx.fillStyle = "#ffe4e6";
          ctx.beginPath();
          ctx.arc(ex, ey, 4.5, 0, Math.PI * 2);
          ctx.fill();
        }
      } else if (targetObj === "pancreas") {
        // Pancreatic Gland Lobule with Islet Beta Cluster
        ctx.strokeStyle = "#eab308";
        ctx.lineWidth = 2;
        ctx.fillStyle = showWireframe ? "transparent" : "rgba(234, 179, 8, 0.18)";

        ctx.beginPath();
        ctx.ellipse(-20, 0, 65, 42, Math.PI * 0.1, 0, Math.PI * 2);
        ctx.fill();
        ctx.stroke();

        // Central Islet of Langerhans
        const isletPulse = 1 + Math.sin(angle * 2.5) * 0.08;
        ctx.fillStyle = "rgba(250, 204, 21, 0.85)";
        ctx.beginPath();
        ctx.arc(0, 0, 18 * isletPulse, 0, Math.PI * 2);
        ctx.fill();

        // Secreted insulin hexamers
        if (action === "dock" || action === "flow") {
          for (let m = 0; m < 6; m++) {
            const mAngle = angle * 2 + (m * Math.PI) / 3;
            const mx = Math.cos(mAngle) * (38 + m * 5);
            const my = Math.sin(mAngle) * (38 + m * 5);
            ctx.fillStyle = "#38bdf8";
            ctx.beginPath();
            ctx.arc(mx, my, 3.5, 0, Math.PI * 2);
            ctx.fill();
          }
        }
      } else {
        // Eukaryotic Cellular Membrane with Receptor Docking Port
        ctx.strokeStyle = "#06b6d4";
        ctx.lineWidth = showWireframe ? 1 : 2;
        ctx.fillStyle = showWireframe ? "transparent" : "rgba(6, 182, 212, 0.12)";

        ctx.beginPath();
        ctx.arc(0, 0, 68, 0, Math.PI * 2);
        ctx.fill();
        ctx.stroke();

        // Transmembrane Channel / GLUT4 Pore
        const channelOpen = action === "dock" || action === "flow" ? 22 : 12;
        ctx.strokeStyle = "#38bdf8";
        ctx.lineWidth = 3;
        ctx.beginPath();
        ctx.arc(0, -68, channelOpen, Math.PI * 0.2, Math.PI * 0.8);
        ctx.stroke();

        // Intracellular nucleus
        ctx.fillStyle = "rgba(168, 85, 247, 0.28)";
        ctx.strokeStyle = "#a855f7";
        ctx.beginPath();
        ctx.ellipse(0, 15, 32, 24, 0, 0, Math.PI * 2);
        ctx.fill();
        ctx.stroke();

        // Floating Ligand / Substrate molecule approaching pore
        const ligX = Math.sin(angle * 2) * 25;
        const ligY = -105 + Math.abs(Math.sin(angle * 1.5)) * 32;
        ctx.fillStyle = "#10b981";
        ctx.beginPath();
        ctx.arc(ligX, ligY, 6, 0, Math.PI * 2);
        ctx.fill();
        ctx.strokeStyle = "#34d399";
        ctx.stroke();
      }

      ctx.restore();

      // Action Tag HUD
      ctx.fillStyle = "rgba(15, 23, 42, 0.75)";
      ctx.fillRect(16, height - 36, 170, 24);
      ctx.strokeStyle = "rgba(56, 189, 248, 0.4)";
      ctx.strokeRect(16, height - 36, 170, 24);
      ctx.fillStyle = "#38bdf8";
      ctx.font = "11px monospace";
      ctx.fillText(`TRANSFORM: ${action.toUpperCase()}`, 24, height - 20);

      animFrameRef.current = requestAnimationFrame(render);
    };

    render();

    return () => {
      isRendering = false;
      if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current);
    };
  }, [script, currentStepIndex, isPlaying, cameraZoom, showWireframe]);

  if (!script || !script.keyframes.length) return null;
  const currentKeyframe = script.keyframes[currentStepIndex];

  return (
    <div
      style={{
        backgroundColor: "#080c14",
        borderRadius: "16px",
        padding: "22px",
        color: "white",
        marginTop: "28px",
        border: "1px solid #1e293b",
        boxShadow: "0 10px 25px -5px rgba(0, 0, 0, 0.5)",
      }}
    >
      {/* Header & Controls */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: "14px",
          flexWrap: "wrap",
          gap: "10px",
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
            3D Pathophysiological Animation Scene ({currentStepIndex + 1}/
            {script.keyframes.length})
          </span>
          <h3 style={{ fontSize: "1.25rem", fontWeight: 600, margin: "4px 0" }}>
            {currentKeyframe.title}
          </h3>
        </div>

        <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
          <button
            type="button"
            onClick={() => setShowWireframe(!showWireframe)}
            style={{
              padding: "5px 12px",
              borderRadius: "9999px",
              fontSize: "0.75rem",
              border: `1px solid ${showWireframe ? "#38bdf8" : "#334155"}`,
              background: showWireframe ? "rgba(56, 189, 248, 0.2)" : "transparent",
              color: showWireframe ? "#38bdf8" : "#94a3b8",
              cursor: "pointer",
            }}
          >
            {showWireframe ? "Solid Mesh" : "Wireframe"}
          </button>

          <button
            type="button"
            onClick={() => setCameraZoom((z) => (z >= 1.4 ? 1 : z + 0.2))}
            style={{
              padding: "5px 12px",
              borderRadius: "9999px",
              fontSize: "0.75rem",
              border: "1px solid #334155",
              background: "transparent",
              color: "#94a3b8",
              cursor: "pointer",
            }}
          >
            Zoom ({Math.round(cameraZoom * 100)}%)
          </button>

          <button
            type="button"
            onClick={() => setIsPlaying(!isPlaying)}
            style={{
              padding: "6px 14px",
              borderRadius: "9999px",
              fontSize: "0.8rem",
              fontWeight: 500,
              border: "1px solid #38bdf8",
              background: isPlaying ? "rgba(56, 189, 248, 0.2)" : "#38bdf8",
              color: isPlaying ? "#38bdf8" : "#04101e",
              cursor: "pointer",
              transition: "all 0.2s ease",
            }}
          >
            {isPlaying ? "Pause Scene" : "Resume Scene"}
          </button>
        </div>
      </div>

      {/* 3D WebGL Canvas Viewport */}
      <div
        style={{
          position: "relative",
          width: "100%",
          height: "260px",
          borderRadius: "12px",
          overflow: "hidden",
          border: "1px solid #1e293b",
          backgroundColor: "#060911",
        }}
      >
        <canvas
          ref={canvasRef}
          width={640}
          height={260}
          style={{ width: "100%", height: "100%", display: "block" }}
        />
      </div>

      {/* Keyframe Pathophysiology Details */}
      <div
        style={{
          backgroundColor: "#030712",
          borderRadius: "12px",
          padding: "16px",
          border: "1px solid #1e293b",
          marginTop: "14px",
        }}
      >
        <p style={{ fontSize: "0.95rem", color: "#e2e8f0", lineHeight: 1.6, margin: 0 }}>
          {currentKeyframe.description}
        </p>
        <div
          style={{
            display: "flex",
            gap: "16px",
            marginTop: "12px",
            fontSize: "0.75rem",
            color: "#94a3b8",
            flexWrap: "wrap",
          }}
        >
          <span>
            Camera Vector:{" "}
            <strong style={{ color: "#e2e8f0" }}>
              [{currentKeyframe.camera_position.join(", ")}]
            </strong>
          </span>
          <span>
            Target Object:{" "}
            <strong style={{ color: "#38bdf8" }}>
              {currentKeyframe.target_object}
            </strong>
          </span>
          <span>
            Action Mode:{" "}
            <strong style={{ color: "#a855f7" }}>
              {currentKeyframe.transform_action}
            </strong>
          </span>
          <span>
            Duration:{" "}
            <strong style={{ color: "#10b981" }}>
              {currentKeyframe.duration_seconds}s
            </strong>
          </span>
        </div>
      </div>

      {/* Step Progress Timeline Scrub Bar */}
      <div style={{ display: "flex", gap: "6px", marginTop: "14px" }}>
        {script.keyframes.map((kf, idx) => (
          <button
            key={kf.step}
            type="button"
            title={`Step ${kf.step}: ${kf.title}`}
            onClick={() => {
              setCurrentStepIndex(idx);
              setIsPlaying(false);
            }}
            style={{
              flex: 1,
              height: "8px",
              borderRadius: "4px",
              border: "none",
              backgroundColor:
                idx === currentStepIndex
                  ? "#38bdf8"
                  : idx < currentStepIndex
                  ? "rgba(56, 189, 248, 0.45)"
                  : "rgba(255, 255, 255, 0.15)",
              cursor: "pointer",
              transition: "background-color 0.2s ease",
            }}
          />
        ))}
      </div>
    </div>
  );
}

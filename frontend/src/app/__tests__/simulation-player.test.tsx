/**
 * Unit tests for SimulationPlayer component.
 *
 * Verifies:
 *  - Initial render with fetched simulation trajectory
 *  - Sliders for simulation parameters exist and update state
 *  - Trajectory steps render in the UI
 *  - Handles API failure gracefully
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import React from "react";
import SimulationPlayer from "@/components/SimulationPlayer";

describe("SimulationPlayer", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("renders trajectory when simulation API returns data", async () => {
    globalThis.fetch = vi.fn(() =>
      Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            title: "Pancreatic Beta Cell & Glucose Regulation Simulation",
            simulation_type: "glucose",
            total_steps: 2,
            trajectory: [
              {
                step: 1,
                time_minutes: 15,
                blood_glucose_mg_dl: 115.2,
                serum_insulin_uIU_ml: 12.0,
                state_summary: "Normoglycemia",
              },
              {
                step: 2,
                time_minutes: 30,
                blood_glucose_mg_dl: 135.5,
                serum_insulin_uIU_ml: 22.0,
                state_summary: "Normoglycemia",
              },
            ],
          }),
      })
    ) as any;

    render(<SimulationPlayer topic="diabetes" />);

    await waitFor(() => {
      expect(
        screen.getByText("Pancreatic Beta Cell & Glucose Regulation Simulation")
      ).toBeInTheDocument();
      expect(screen.getByText("115.2 mg/dL")).toBeInTheDocument();
      expect(screen.getByText("135.5 mg/dL")).toBeInTheDocument();
    });
  });

  it("slider controls update parameter values", async () => {
    globalThis.fetch = vi.fn(() =>
      Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            title: "Test Simulation",
            trajectory: [
              { step: 1, time_minutes: 15, blood_glucose_mg_dl: 100 },
            ],
          }),
      })
    ) as any;

    const { container } = render(<SimulationPlayer topic="glucose" />);

    await waitFor(() => {
      expect(screen.getByText("Test Simulation")).toBeInTheDocument();
    });

    const sliders = container.querySelectorAll("input[type='range']");
    expect(sliders.length).toBe(2);

    fireEvent.change(sliders[0], { target: { value: "100" } });
    expect(screen.getByText(/Carbohydrate Intake: 100g/)).toBeInTheDocument();
  });

  it("does not render when trajectory is empty", async () => {
    globalThis.fetch = vi.fn(() =>
      Promise.resolve({
        ok: false,
        json: () => Promise.resolve({}),
      })
    ) as any;

    const { container } = render(<SimulationPlayer topic="unknown" />);
    expect(container.firstChild).toBeNull();
  });
});

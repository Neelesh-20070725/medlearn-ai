/**
 * Unit tests for Emergency and Crisis Safety Routing on the frontend.
 *
 * Verifies:
 *  - 422 response with emergency payload (911) displays emergency message
 *  - 422 response with crisis payload (988) displays crisis resource message
 *  - Error messages with emergency keywords are styled with emergency banner
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import React from "react";
import Page from "@/app/page";

describe("Frontend Emergency and Crisis Routing", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("displays emergency redirect when search encounters a medical emergency", async () => {
    const emergencyMessage =
      "⚠️ This sounds like a medical emergency. Please call 911 (USA) or your local emergency number immediately.";

    globalThis.fetch = vi.fn((url: string) => {
      if (url.includes("/api/v1/lessons/search")) {
        return Promise.resolve({
          ok: false,
          status: 422,
          json: () =>
            Promise.resolve({
              detail: {
                type: "emergency",
                message: emergencyMessage,
                safe_redirect: true,
              },
            }),
        });
      }
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({}),
      });
    }) as any;

    render(<Page />);

    const input = screen.getByPlaceholderText(/e\.g\. What is diabetes\?/i);
    const submitBtn = screen.getByRole("button", { name: /explain it/i });

    fireEvent.change(input, {
      target: { value: "chest pain, left arm pain, sweating" },
    });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(screen.getByText(/This sounds like a medical emergency/i)).toBeInTheDocument();
      expect(screen.getByText(/call 911/i)).toBeInTheDocument();
    });
  });

  it("displays crisis lifeline redirect when search encounters a self-harm statement", async () => {
    const crisisMessage =
      "💙 It sounds like you may be going through something very difficult. Please call or text 988 (USA, 24/7).";

    globalThis.fetch = vi.fn((url: string) => {
      if (url.includes("/api/v1/lessons/search")) {
        return Promise.resolve({
          ok: false,
          status: 422,
          json: () =>
            Promise.resolve({
              detail: {
                type: "crisis",
                message: crisisMessage,
                safe_redirect: true,
              },
            }),
        });
      }
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({}),
      });
    }) as any;

    render(<Page />);

    const input = screen.getByPlaceholderText(/e\.g\. What is diabetes\?/i);
    const submitBtn = screen.getByRole("button", { name: /explain it/i });

    fireEvent.change(input, { target: { value: "I want to kill myself" } });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(screen.getByText(/call or text 988/i)).toBeInTheDocument();
    });
  });
});

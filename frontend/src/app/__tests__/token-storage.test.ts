/**
 * Tests for the localStorage-backed auth token helpers (loadTokens,
 * saveTokens, clearTokens). Pure, deterministic - jsdom provides a real
 * localStorage implementation, so these exercise actual browser storage
 * semantics, not a mock.
 */
import { describe, it, expect, beforeEach } from "vitest";
import { loadTokens, saveTokens, clearTokens } from "../page";

describe("token storage", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("returns null when nothing has been saved", () => {
    expect(loadTokens()).toBeNull();
  });

  it("saves and loads tokens round-trip correctly", () => {
    const tokens = { access_token: "access123", refresh_token: "refresh456" };
    saveTokens(tokens);
    expect(loadTokens()).toEqual(tokens);
  });

  it("clearTokens removes the saved session", () => {
    saveTokens({ access_token: "a", refresh_token: "b" });
    clearTokens();
    expect(loadTokens()).toBeNull();
  });

  it("returns null (not a crash) when localStorage contains malformed JSON", () => {
    window.localStorage.setItem("medlearn_tokens", "{not valid json");
    expect(loadTokens()).toBeNull();
  });

  it("overwriting a saved session replaces it, not merges it", () => {
    saveTokens({ access_token: "old-access", refresh_token: "old-refresh" });
    saveTokens({ access_token: "new-access", refresh_token: "new-refresh" });
    expect(loadTokens()).toEqual({ access_token: "new-access", refresh_token: "new-refresh" });
  });
});

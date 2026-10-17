/**
 * Tests for authFetch - the wrapper that attaches the access token to a
 * request and silently retries once via the refresh token on a 401.
 * This is the most non-trivial piece of client-side auth logic in the
 * app, so it's the highest-value thing to test here: a bug in this
 * function would mean every signed-in feature (bookmarks, quiz submit,
 * tutor history) silently breaks the moment a token expires.
 */
import { describe, it, expect, beforeEach, vi } from "vitest";
import { authFetch, saveTokens } from "../page";

describe("authFetch", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.restoreAllMocks();
  });

  it("returns null immediately when there is no saved session", async () => {
    const fetchSpy = vi.spyOn(global, "fetch");
    const result = await authFetch("/api/v1/users/me/history");
    expect(result).toBeNull();
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("attaches the Authorization header from the saved access token", async () => {
    saveTokens({ access_token: "my-access-token", refresh_token: "my-refresh-token" });
    const fetchSpy = vi.spyOn(global, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), { status: 200 })
    );

    await authFetch("/api/v1/users/me/history");

    const [, init] = fetchSpy.mock.calls[0];
    const headers = init?.headers as Record<string, string>;
    expect(headers.Authorization).toBe("Bearer my-access-token");
  });

  it("returns the response directly on a non-401 result, without attempting a refresh", async () => {
    saveTokens({ access_token: "access", refresh_token: "refresh" });
    const fetchSpy = vi.spyOn(global, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ data: "ok" }), { status: 200 })
    );

    const result = await authFetch("/api/v1/users/me/history");
    expect(result?.status).toBe(200);
    expect(fetchSpy).toHaveBeenCalledTimes(1); // no refresh attempt
  });

  it("on a 401, silently refreshes and retries the original request once", async () => {
    saveTokens({ access_token: "expired-access", refresh_token: "valid-refresh" });

    const fetchSpy = vi.spyOn(global, "fetch");
    fetchSpy
      .mockResolvedValueOnce(new Response(null, { status: 401 })) // original request fails
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ access_token: "new-access", refresh_token: "new-refresh" }), { status: 200 })
      ) // refresh succeeds
      .mockResolvedValueOnce(new Response(JSON.stringify({ data: "ok" }), { status: 200 })); // retry succeeds

    const result = await authFetch("/api/v1/users/me/history");

    expect(fetchSpy).toHaveBeenCalledTimes(3);
    expect(result?.status).toBe(200);

    // the retried request must use the NEW access token, not the expired one
    const [, retryInit] = fetchSpy.mock.calls[2];
    const retryHeaders = retryInit?.headers as Record<string, string>;
    expect(retryHeaders.Authorization).toBe("Bearer new-access");
  });

  it("persists the refreshed tokens to storage after a successful silent refresh", async () => {
    saveTokens({ access_token: "expired-access", refresh_token: "valid-refresh" });

    vi.spyOn(global, "fetch")
      .mockResolvedValueOnce(new Response(null, { status: 401 }))
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ access_token: "new-access", refresh_token: "new-refresh" }), { status: 200 })
      )
      .mockResolvedValueOnce(new Response(JSON.stringify({}), { status: 200 }));

    await authFetch("/api/v1/users/me/history");

    const stored = window.localStorage.getItem("medlearn_tokens");
    expect(stored).toContain("new-access");
  });

  it("clears the session and returns null when the refresh token itself is rejected", async () => {
    saveTokens({ access_token: "expired-access", refresh_token: "dead-refresh" });

    vi.spyOn(global, "fetch")
      .mockResolvedValueOnce(new Response(null, { status: 401 })) // original request fails
      .mockResolvedValueOnce(new Response(null, { status: 401 })); // refresh ALSO fails - dead session

    const result = await authFetch("/api/v1/users/me/history");

    expect(result).toBeNull();
    expect(window.localStorage.getItem("medlearn_tokens")).toBeNull();
  });
});

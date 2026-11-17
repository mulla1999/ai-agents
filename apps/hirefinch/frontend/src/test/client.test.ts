import { describe, expect, it, vi } from "vitest";
import { ApiError, api, setUnauthenticatedHandler } from "../api/client";
import { mockFetch } from "./utils";

describe("api client", () => {
  it("sends the CSRF cookie as X-CSRF-Token on POST, not on GET", async () => {
    document.cookie = "job_agent_csrf=tok-123";
    const calls = mockFetch(() => ({ json: { ok: true } }));

    await api("/jobs");
    await api("/jobs/1/approve", { method: "POST", body: {} });

    expect(calls[0].headers["X-CSRF-Token"]).toBeUndefined();
    expect(calls[1].headers["X-CSRF-Token"]).toBe("tok-123");
  });

  it("calls the unauthenticated handler on a 401, except for /auth/ paths", async () => {
    const handler = vi.fn();
    setUnauthenticatedHandler(handler);
    mockFetch(() => ({ status: 401, json: { error: "unauthenticated", message: "sign in" } }));

    await expect(api("/jobs")).rejects.toBeInstanceOf(ApiError);
    expect(handler).toHaveBeenCalledTimes(1);

    await expect(api("/auth/login", { method: "POST", body: {} })).rejects.toMatchObject({ status: 401, code: "unauthenticated" });
    expect(handler).toHaveBeenCalledTimes(1);
  });
});

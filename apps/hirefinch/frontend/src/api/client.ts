// Fetch wrapper: same-origin cookies for the session, CSRF header on every state-changing request.

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
  ) {
    super(message);
  }
}

function readCookie(name: string): string | undefined {
  return document.cookie
    .split("; ")
    .find((part) => part.startsWith(`${name}=`))
    ?.slice(name.length + 1);
}

type Method = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

// Set by the auth layer so any 401 shows the sign-in screen.
let onUnauthenticated: (() => void) | null = null;
export function setUnauthenticatedHandler(handler: () => void): void {
  onUnauthenticated = handler;
}

export async function api<T>(
  path: string,
  options: { method?: Method; body?: unknown; form?: FormData } = {},
): Promise<T> {
  const method = options.method ?? (options.body !== undefined || options.form ? "POST" : "GET");
  const headers: Record<string, string> = { Accept: "application/json" };
  if (options.body !== undefined) headers["Content-Type"] = "application/json";
  if (method !== "GET") headers["X-CSRF-Token"] = readCookie("job_agent_csrf") ?? "";

  const response = await fetch(`/api${path}`, {
    method,
    headers,
    credentials: "same-origin",
    body: options.form ?? (options.body === undefined ? undefined : JSON.stringify(options.body)),
  });
  if (response.status === 204) return undefined as T;

  const data = await response.json().catch(() => null);
  if (!response.ok) {
    if (response.status === 401 && !path.startsWith("/auth/")) onUnauthenticated?.();
    throw new ApiError(response.status, data?.error ?? "error", errorMessage(data, response.statusText));
  }
  return data as T;
}

function errorMessage(data: unknown, fallback: string): string {
  if (data && typeof data === "object") {
    const body = data as { message?: string; detail?: unknown };
    if (body.message) return body.message;
    if (typeof body.detail === "string") return body.detail;
    if (Array.isArray(body.detail)) {
      return body.detail
        .map((d: { loc?: unknown[]; msg?: string }) => `${(d.loc ?? []).slice(1).join(".")}: ${d.msg}`)
        .join("; ");
    }
  }
  return fallback;
}

export function ensureCsrfToken(): Promise<unknown> {
  return api("/auth/csrf");
}

/** Build a query string, skipping empty values. */
export function qs(params: Record<string, string | number | boolean | null | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "" || value === false) continue;
    search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

/** POST JSON and get a file back (e.g. a PDF preview), with the same CSRF and error handling as `api`. */
export async function apiBlob(path: string, body: unknown): Promise<Blob> {
  const response = await fetch(`/api${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": readCookie("job_agent_csrf") ?? "" },
    credentials: "same-origin",
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => null);
    if (response.status === 401) onUnauthenticated?.();
    throw new ApiError(response.status, data?.error ?? "error", errorMessage(data, response.statusText));
  }
  return response.blob();
}

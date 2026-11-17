// Talks to your HireFinch server with the extension key. Settings live in chrome.storage.local
// (this device only; never synced).
"use strict";

export async function getSettings() {
  const { server = "", token = "" } = await chrome.storage.local.get(["server", "token"]);
  return { server: server.replace(/\/+$/, ""), token };
}

export function originPattern(server) {
  const u = new URL(server);
  return `${u.protocol}//${u.hostname}/*`;
}

export async function call(path, { method = "GET", body, server, token } = {}) {
  if (!server || !token) {
    const s = await getSettings();
    server = server || s.server;
    token = token || s.token;
  }
  if (!server || !token) throw new Error("Open the extension settings and add your HireFinch address and key.");
  let response;
  try {
    response = await fetch(`${server}/api/extension${path}`, {
      method,
      headers: { Authorization: `Bearer ${token}`, Accept: "application/json", ...(body ? { "Content-Type": "application/json" } : {}) },
      body: body ? JSON.stringify(body) : undefined,
      credentials: "omit", // the key is the only credential; cookies are never sent
    });
  } catch {
    throw new Error(`Cannot reach ${server}. Is HireFinch running, and did you allow access in settings?`);
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.message || `HireFinch answered ${response.status}`);
  return data;
}

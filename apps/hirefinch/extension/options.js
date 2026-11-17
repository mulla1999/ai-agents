import { call, getSettings, originPattern } from "./lib/api.js";

const EMBEDDED = ["https://boards.greenhouse.io/*", "https://job-boards.greenhouse.io/*", "https://jobs.lever.co/*", "https://jobs.ashbyhq.com/*"];
const $ = (id) => document.getElementById(id);
let offered = null; // kept in memory so Accept asks Chrome for access straight from the click

(async () => {
  const { server, token } = await getSettings();
  $("server").value = server || "http://127.0.0.1:5173";
  $("token").placeholder = token ? "saved (leave blank to keep)" : "jae_…";
  $("embedded").checked = await chrome.permissions.contains({ origins: EMBEDDED });
  const { autoSubmit = true } = await chrome.storage.local.get("autoSubmit");
  $("autoSubmit").checked = autoSubmit;
  // A key offered by "Connect extension" on the HireFinch site (parked by background.js).
  const { pending } = await chrome.storage.session.get("pending");
  if (pending) {
    offered = pending;
    $("offerServer").textContent = pending.server;
    $("offer").hidden = false;
    // Offered keys come from the site's own button, which works with Greenhouse, Lever and Ashby too.
    $("embedded").checked = true;
  }
})();

$("autoSubmit").addEventListener("change", () => chrome.storage.local.set({ autoSubmit: $("autoSubmit").checked }));

// Checks the address and key, asks Chrome for access (must run in a click handler), and saves them.
async function connect(rawServer, rawToken, status) {
  status.className = "status";
  let server;
  try {
    server = new URL(rawServer.trim()).origin;
  } catch {
    status.textContent = "Enter the full address, e.g. https://jobs.yourdomain.com";
    return false;
  }
  const local = ["127.0.0.1", "localhost"].includes(new URL(server).hostname);
  if (!server.startsWith("https://") && !local) {
    status.textContent = "Use an https:// address (plain http only for this computer).";
    return false;
  }
  // Ask only for your server (and, if ticked, the embedded-form hosts).
  const origins = [originPattern(server), ...($("embedded").checked ? EMBEDDED : [])];
  if (!(await chrome.permissions.request({ origins }))) {
    status.textContent = "Permission was not granted, so the extension cannot reach HireFinch.";
    return false;
  }
  if (!$("embedded").checked) await chrome.permissions.remove({ origins: EMBEDDED }).catch(() => undefined);
  const token = rawToken.trim() || (await getSettings()).token;
  if (!/^jae_[\w-]{20,}$/.test(token)) {
    status.textContent = "That does not look like an extension key (it starts with jae_).";
    return false;
  }
  try {
    const me = await call("/me", { server, token });
    await chrome.storage.local.set({ server, token });
    $("server").value = server;
    $("token").value = "";
    $("token").placeholder = "saved (leave blank to keep)";
    status.className = "status ok";
    status.textContent = `Connected as ${me.email}. You can close this tab.`;
    return true;
  } catch (err) {
    status.textContent = err.message;
    return false;
  }
}

$("accept").addEventListener("click", async () => {
  if (!offered) return;
  if (await connect(offered.server, offered.token, $("offerStatus"))) {
    await chrome.storage.session.remove("pending");
    $("accept").hidden = $("reject").hidden = true;
  }
});

$("reject").addEventListener("click", async () => {
  await chrome.storage.session.remove("pending");
  $("offer").hidden = true;
});

$("form").addEventListener("submit", async (e) => {
  e.preventDefault();
  await connect($("server").value, $("token").value, $("status"));
});

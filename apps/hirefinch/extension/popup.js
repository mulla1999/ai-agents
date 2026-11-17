import { call, getSettings } from "./lib/api.js";

const body = document.getElementById("body");
document.getElementById("settings").addEventListener("click", (e) => {
  e.preventDefault();
  chrome.runtime.openOptionsPage();
});

// Built with DOM nodes, never innerHTML: titles and labels come from job postings and web pages.
function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v);
  }
  for (const c of children.flat()) if (c != null) node.append(c);
  return node;
}

function show(...nodes) {
  body.replaceChildren(...nodes);
}

function error(message) {
  show(el("p", { class: "status" }, message));
}

async function tab() {
  const [t] = await chrome.tabs.query({ active: true, currentWindow: true });
  return t;
}

async function main() {
  const { server, token } = await getSettings();
  if (!server || !token) {
    show(el("p", {}, "Connect the extension to your HireFinch first."), el("button", { class: "primary", onclick: () => chrome.runtime.openOptionsPage() }, "Open settings"));
    return;
  }
  const t = await tab();
  if (!t || !/^https?:/.test(t.url || "")) {
    error("Open the employer's application form in this tab first.");
    return;
  }
  let list;
  try {
    list = await call(`/applications?url=${encodeURIComponent(t.url)}`);
  } catch (e) {
    error(e.message);
    return;
  }
  if (list.blocked) {
    error(list.message);
    return;
  }
  if (!list.items.length) {
    show(el("p", {}, "No applications are waiting to be filled in."), el("p", { class: "muted" }, "Prepared applications for jobs on employer sites appear here."));
    return;
  }
  const match = list.items.find((i) => i.matches_page);
  const select = el("select", { "aria-label": "Application" },
    list.items.map((i) => el("option", { value: String(i.id) }, `${i.matches_page ? "✓ " : ""}${i.title} · ${i.company}`)));
  if (match) select.value = String(match.id);
  const { autoSubmit = true } = await chrome.storage.local.get("autoSubmit");
  const button = el("button", { class: "primary", onclick: () => fill(t, Number(select.value), button) }, autoSubmit ? "Fill and submit if certain" : "Fill this form");
  show(
    el("p", { class: match ? "ok" : "muted" }, match ? "This page matches one of your applications." : "Pick the application for this form:"),
    select,
    button,
    el("p", { class: "muted small" }, autoSubmit ? "Submits only when every required field is filled, the resume is attached and no CAPTCHA shows, after a 5-second countdown." : "Green outline: filled. Amber: needs you. Check every field before submitting."),
  );
}

async function fill(t, appId, button) {
  button.disabled = true;
  button.textContent = "Filling…";
  let data;
  try {
    data = await call(`/applications/${appId}/autofill?url=${encodeURIComponent(t.url)}`);
  } catch (e) {
    error(e.message);
    return;
  }
  const { autoSubmit = true } = await chrome.storage.local.get("autoSubmit");
  if (autoSubmit) {
    // The background worker fills, submits only if certain, and keeps watching if this popup closes.
    button.textContent = "Filling and checking…";
    const outcome = await chrome.runtime.sendMessage({ type: "fill-and-submit", tabId: t.id, data });
    if (outcome && outcome.confirmed) {
      show(el("p", { class: "ok" }, "Applied ✓"), el("p", { class: "muted" }, "Recorded in HireFinch; a confirmation email is on its way."));
      return;
    }
    if (outcome && outcome.submitted) {
      show(el("p", { class: "warn" }, "Submitted, but no confirmation page was seen."), el("p", { class: "muted" }, "If it went through, record it:"),
        ...appliedForm(appId));
      return;
    }
    show(el("p", { class: "warn" }, "Filled, not submitted:"), el("ul", {}, ((outcome && outcome.reasons) || []).map((r) => el("li", {}, r))),
      el("p", { class: "muted small" }, "Finish the form on the page and submit it. Afterwards:"), ...appliedForm(appId));
    return;
  }
  let results;
  try {
    await chrome.scripting.executeScript({ target: { tabId: t.id, allFrames: true }, files: ["lib/matcher.js", "lib/fill.js"] });
    results = await chrome.scripting.executeScript({ target: { tabId: t.id, allFrames: true }, func: (d) => globalThis.__hireFinchFill(d), args: [data] });
  } catch (e) {
    error(`This page cannot be filled (${e.message}). Some forms are embedded from another site: allow those in Settings, or open the form directly.`);
    return;
  }
  const reports = results.map((r) => r.result).filter(Boolean);
  const filled = reports.flatMap((r) => r.filled);
  const left = [...new Set(reports.flatMap((r) => r.left))];
  const resume = reports.some((r) => r.resume);
  const sensitive = reports.reduce((n, r) => n + r.skipped_sensitive, 0);
  if (!filled.length && !resume) {
    show(el("p", { class: "status" }, "No form fields found on this page."), el("p", { class: "muted" }, "Click the employer's Apply button to open the form, then try again."));
    return;
  }
  const ref = el("input", { type: "text", maxlength: "300", placeholder: "Confirmation number (optional)", "aria-label": "Confirmation number" });
  const done = el("button", { onclick: () => applied(appId, ref.value, done) }, "I submitted it");
  show(
    el("p", { class: "ok" }, `Filled ${filled.length} field${filled.length === 1 ? "" : "s"}${resume ? " and attached your tailored resume" : ""}.`),
    !resume && data.resume ? el("p", { class: "status" }, "Attach the resume yourself: no resume upload field was recognised.") : null,
    left.length ? el("div", {}, el("p", { class: "warn" }, "Needs you:"), el("ul", {}, left.slice(0, 8).map((l) => el("li", {}, l)))) : null,
    sensitive ? el("p", { class: "muted small" }, `${sensitive} personal or legal question${sensitive === 1 ? " was" : "s were"} left for you.`) : null,
    el("p", { class: "muted small" }, "Review the form, solve any CAPTCHA, then click the employer's Submit button. Afterwards:"),
    ref,
    done,
  );
}

function appliedForm(appId) {
  const ref = el("input", { type: "text", maxlength: "300", placeholder: "Confirmation number (optional)", "aria-label": "Confirmation number" });
  const done = el("button", { onclick: () => applied(appId, ref.value, done) }, "I submitted it");
  return [ref, done];
}

async function applied(appId, reference, button) {
  button.disabled = true;
  try {
    await call(`/applications/${appId}/applied`, { method: "POST", body: { reference: reference.trim() || null } });
    show(el("p", { class: "ok" }, "Recorded in HireFinch. Good luck!"));
  } catch (e) {
    error(e.message);
  }
}

main();

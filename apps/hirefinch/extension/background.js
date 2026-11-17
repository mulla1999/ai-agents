// Auto-apply. Runs only for a tab you opened with "Auto-apply" in HireFinch: that link carries a
// short-lived signed ticket for one application. It fills the form, and submits only when the form is
// certain (every required field filled, resume attached, no CAPTCHA, one Submit button), after a
// 5-second countdown you can cancel. It records the application only when the employer's
// confirmation page appears; HireFinch then emails you.
import { call, getSettings } from "./lib/api.js";

const MARK = "#hirefinch-apply=";
const SCRIPTS = ["lib/matcher.js", "lib/fill.js", "lib/auto.js"];
const running = new Set(); // tabs with an Auto-apply in progress

async function inject(tabId) {
  await chrome.scripting.executeScript({ target: { tabId }, files: SCRIPTS });
}

async function run(tabId, func, ...args) {
  const [result] = await chrome.scripting.executeScript({ target: { tabId }, func, args });
  return result ? result.result : undefined;
}

function banner(tabId, lines, tone) {
  return run(tabId, (l, t) => globalThis.HireFinchAuto.banner(l, t), lines, tone).catch(() => undefined);
}

/** Fill, check, count down, submit, then watch for the confirmation page. */
export async function submitAndWatch(tabId, data, { automatic }) {
  const { autoSubmit = true } = await chrome.storage.local.get("autoSubmit");
  await inject(tabId);
  const report = await run(tabId, (d) => globalThis.__hireFinchFill(d), data);
  const verdict = await run(tabId, (r) => globalThis.HireFinchAuto.assess(r, r.resume_field), report);
  const title = `${data.job.title} at ${data.job.company}`;
  if (!autoSubmit || !verdict.ready) {
    await banner(tabId, [
      `HireFinch filled ${report.filled.length} field${report.filled.length === 1 ? "" : "s"}${report.resume ? " and attached your resume" : ""}`,
      ...(verdict.ready ? ["Automatic submit is off in the extension settings."] : verdict.reasons.map((r) => `Not submitted: ${r}.`)),
      ...report.left.slice(0, 5).map((l) => `• ${l}`),
      "Finish the form, submit it, then click the extension → I submitted it.",
    ], "warn");
    return { submitted: false, report, reasons: verdict.reasons };
  }
  const go = await run(tabId, (t) => globalThis.HireFinchAuto.countdown(5, t), title);
  if (!go) return { submitted: false, report, reasons: ["cancelled by you"] };
  // Check again just before clicking: the page may have changed during the countdown.
  const again = await run(tabId, () => ({ captcha: globalThis.HireFinchAuto.captchaShowing(), errors: globalThis.HireFinchAuto.errorsShowing() }));
  if (!again || again.captcha || again.errors) {
    const why = again && again.captcha ? "the form now shows a CAPTCHA" : "the form now shows an error";
    await banner(tabId, ["Not submitted", `${why}.`, "Finish it yourself, then use the extension → I submitted it."], "warn");
    return { submitted: false, report, reasons: [why] };
  }
  const clicked = await run(tabId, () => globalThis.HireFinchAuto.clickSubmit());
  if (!clicked) return { submitted: false, report, reasons: ["the Submit button disappeared"] };

  // Watch for up to 45 seconds, across the page change most forms make after submitting.
  for (let i = 0; i < 22; i++) {
    await new Promise((r) => setTimeout(r, 2000));
    let state;
    try {
      await inject(tabId);
      state = await run(tabId, () => ({
        confirmation: globalThis.HireFinchAuto.confirmation(),
        captcha: globalThis.HireFinchAuto.captchaShowing(),
        errors: globalThis.HireFinchAuto.errorsShowing(),
      }));
    } catch {
      continue; // mid-navigation
    }
    if (!state) continue;
    if (state.confirmation) {
      try {
        await call(`/applications/${data.application_id}/applied`, { method: "POST", body: { confirmation_page: state.confirmation, automatic } });
        await banner(tabId, ["Applied ✓", title, "Recorded in HireFinch; a confirmation email is on its way to you."], "ok");
      } catch (e) {
        await banner(tabId, ["Submitted, but not recorded", e.message, "Open the extension and click I submitted it."], "warn");
      }
      return { submitted: true, confirmed: true };
    }
    if (state.captcha) {
      await banner(tabId, ["The site asks for a CAPTCHA", "Solve it and submit; then click the extension → I submitted it."], "warn");
      return { submitted: false, reasons: ["CAPTCHA after submit"] };
    }
    if (state.errors && i >= 1) {
      await banner(tabId, ["The form did not go through", "It shows an error: fix it and submit, then click the extension → I submitted it."], "warn");
      return { submitted: false, reasons: ["form error after submit"] };
    }
  }
  await banner(tabId, ["Submitted, but no confirmation was seen", "Check the page or your email. If it went through, click the extension → I submitted it."], "warn");
  return { submitted: true, confirmed: false };
}

async function autoApply(tabId, url) {
  const ticket = decodeURIComponent(url.slice(url.indexOf(MARK) + MARK.length)).split("&")[0];
  const clean = url.slice(0, url.indexOf(MARK));
  // Drop the ticket from the address bar so a reload does not start again.
  await chrome.scripting.executeScript({ target: { tabId }, func: () => history.replaceState(null, "", location.href.split("#hirefinch-apply=")[0]) }).catch(() => undefined);
  let data;
  try {
    data = await call(`/ticket?t=${encodeURIComponent(ticket)}&url=${encodeURIComponent(clean)}`);
  } catch (e) {
    await inject(tabId).catch(() => undefined);
    await banner(tabId, ["HireFinch could not auto-apply", e.message], "warn");
    return;
  }
  await submitAndWatch(tabId, data, { automatic: true });
}

chrome.tabs.onUpdated.addListener(async (tabId, info, tab) => {
  if (info.status !== "complete" || !tab.url || !tab.url.includes(MARK) || running.has(tabId)) return;
  const { server, token } = await getSettings();
  if (!server || !token) return;
  const origin = new URL(tab.url).origin + "/*";
  if (!(await chrome.permissions.contains({ origins: [origin] }))) {
    chrome.action.setBadgeText({ tabId, text: "!" });
    chrome.action.setTitle({ tabId, title: "Allow Auto-apply for this site in the extension settings, or click Fill this form." });
    return;
  }
  running.add(tabId);
  try {
    await autoApply(tabId, tab.url);
  } finally {
    running.delete(tabId);
  }
});

// The popup's "Fill this form" hands over here, so watching continues if the popup closes.
chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
  if (msg && msg.type === "fill-and-submit" && !running.has(msg.tabId)) {
    running.add(msg.tabId);
    submitAndWatch(msg.tabId, msg.data, { automatic: false })
      .then(reply, (e) => reply({ submitted: false, reasons: [e.message] }))
      .finally(() => running.delete(msg.tabId));
    return true; // async reply
  }
  return false;
});

// The HireFinch site (see externally_connectable) can ask whether the extension is installed, and
// offer a key with "Connect extension". Any trycloudflare.com page can send these, so an offered key
// is only parked here: it is saved after you confirm the address on the extension's settings page.
chrome.runtime.onMessageExternal.addListener((msg, sender, reply) => {
  const server = sender.origin;
  if (msg && msg.type === "ping") {
    getSettings().then((s) => reply({ installed: true, version: chrome.runtime.getManifest().version, connected: !!s.token && s.server === server }));
    return true;
  }
  if (msg && msg.type === "connect" && /^jae_[\w-]{20,}$/.test(msg.token || "") && server) {
    chrome.storage.session
      .set({ pending: { server, token: msg.token } })
      .then(() => chrome.runtime.openOptionsPage())
      .then(() => reply({ opened: true }), () => reply({ opened: false }));
    return true;
  }
  return false;
});

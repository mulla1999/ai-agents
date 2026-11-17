// In-page helpers for Auto-apply: is the filled form certain enough to submit, a cancellable
// countdown, clicking the form's own Submit button, and recognising the employer's confirmation page.
// A CAPTCHA challenge or any unanswered required field means: do not submit, hand over to you.
(function (root) {
  "use strict";

  function shown(el) {
    const r = el.getBoundingClientRect ? el.getBoundingClientRect() : { width: 1, height: 1 };
    const s = root.getComputedStyle ? root.getComputedStyle(el) : null;
    return r.width > 2 && r.height > 2 && !(s && (s.display === "none" || s.visibility === "hidden"));
  }

  /** A CAPTCHA you would have to solve (reCAPTCHA checkbox/challenge, hCaptcha, Turnstile). The
   *  invisible reCAPTCHA badge is not one: the site checks it itself when the form is sent. */
  function captchaShowing(doc) {
    doc = doc || root.document;
    const frames = [...doc.querySelectorAll("iframe")].filter((f) => {
      const src = f.src || "";
      if (/hcaptcha\.com|challenges\.cloudflare\.com|captcha/i.test(src) && !/recaptcha/i.test(src)) return shown(f);
      if (/recaptcha/i.test(src)) return !/size=invisible/.test(src) && shown(f) && !/badge/i.test(f.title || "");
      return false;
    });
    const widgets = [...doc.querySelectorAll(".g-recaptcha:not([data-size='invisible']), .h-captcha, .cf-turnstile")].filter(shown);
    return frames.length > 0 || widgets.length > 0;
  }

  const SUBMIT_TEXT = /^(submit( (my |your )?application)?|apply( now)?|send( my)? application|submit & apply)$/i;

  /** The one Submit button of the form that holds the filled fields, or null when unclear. */
  function submitButton(doc) {
    doc = doc || root.document;
    const filled = doc.querySelector("[style*='rgb(16, 185, 129)'], [style*='#10b981']");
    const scope = (filled && filled.closest("form")) || doc.querySelector("form") || doc;
    const candidates = [...scope.querySelectorAll("button, input[type=submit]")].filter((b) => {
      if (b.disabled || !shown(b)) return false;
      const text = (b.innerText || b.value || b.textContent || "").replace(/\s+/g, " ").trim();
      return SUBMIT_TEXT.test(text) || (b.type === "submit" && /submit|apply/i.test(text));
    });
    return candidates.length === 1 ? candidates[0] : null;
  }

  function errorsShowing(doc) {
    doc = doc || root.document;
    return [...doc.querySelectorAll("[aria-invalid='true'], .error, .field-error, .error-message, [class*='error']")]
      .some((e) => shown(e) && (e.getAttribute("aria-invalid") === "true" || (e.textContent || "").trim().length > 2));
  }

  const CONFIRMED = /(thank(s| you) for (applying|your (application|interest))|application (has been |was )?(submitted|received|sent)|we('ve| have) received your application|your application (is|has been) (submitted|received|complete)|successfully (applied|submitted))/i;

  function confirmation(doc) {
    doc = doc || root.document;
    const text = (doc.body && (doc.body.innerText || doc.body.textContent)) || "";
    const m = text.match(CONFIRMED);
    if (!m) return null;
    const start = Math.max(0, m.index - 60);
    return text.slice(start, m.index + m[0].length + 120).replace(/\s+/g, " ").trim().slice(0, 300);
  }

  /** Decide whether to submit, from the fill report. Returns {ready, reasons}. */
  function assess(report, hasResumeField, doc) {
    const reasons = [];
    if (report.left.length) reasons.push(`${report.left.length} field${report.left.length === 1 ? "" : "s"} still need you`);
    if (hasResumeField && !report.resume) reasons.push("the resume could not be attached");
    if (captchaShowing(doc)) reasons.push("the form shows a CAPTCHA");
    if (!submitButton(doc)) reasons.push("the Submit button could not be identified");
    if (errorsShowing(doc)) reasons.push("the form shows an error");
    return { ready: reasons.length === 0, reasons };
  }

  function banner(lines, tone) {
    const old = root.document.getElementById("hirefinch-banner");
    if (old) old.remove();
    const host = root.document.createElement("div");
    host.id = "hirefinch-banner";
    const shadow = host.attachShadow({ mode: "closed" });
    const colors = { info: "#4f46e5", ok: "#047857", warn: "#b45309" }[tone || "info"];
    const box = root.document.createElement("div");
    box.setAttribute("style", `position:fixed;z-index:2147483647;right:16px;bottom:16px;max-width:360px;background:#fff;color:#0f172a;border:2px solid ${colors};border-radius:14px;padding:12px 14px;font:13px/1.45 system-ui,sans-serif;box-shadow:0 10px 30px rgba(15,23,42,.25)`);
    // Built from text nodes only: nothing from the page or the server becomes markup.
    for (const [i, line] of lines.entries()) {
      const p = root.document.createElement(i === 0 ? "strong" : "div");
      p.textContent = line;
      p.setAttribute("style", i === 0 ? `display:block;color:${colors};margin-bottom:4px` : "margin-top:2px");
      box.appendChild(p);
    }
    shadow.appendChild(box);
    root.document.documentElement.appendChild(host);
    return { box, host };
  }

  /** Show a countdown; resolves true to submit, false if you cancelled. */
  function countdown(seconds, title) {
    return new Promise((resolve) => {
      const { box, host } = banner([`HireFinch will submit in ${seconds}s`, title, "Every required field is filled and your tailored resume is attached."], "info");
      const button = root.document.createElement("button");
      button.textContent = "Cancel";
      button.setAttribute("style", "margin-top:8px;padding:6px 12px;border-radius:8px;border:1px solid #cbd5e1;background:#fff;cursor:pointer;font:inherit");
      box.appendChild(button);
      let left = seconds;
      const timer = setInterval(() => {
        left -= 1;
        box.firstChild.textContent = `HireFinch will submit in ${left}s`;
        if (left <= 0) {
          clearInterval(timer);
          host.remove();
          resolve(true);
        }
      }, 1000);
      button.addEventListener("click", () => {
        clearInterval(timer);
        banner(["Cancelled", "Nothing was submitted. Review the form and submit it yourself when ready."], "warn");
        resolve(false);
      });
    });
  }

  function clickSubmit(doc) {
    const button = submitButton(doc);
    if (!button) return false;
    button.click();
    return true;
  }

  root.HireFinchAuto = { assess, captchaShowing, submitButton, errorsShowing, confirmation, countdown, clickSubmit, banner };
})(typeof globalThis !== "undefined" ? globalThis : this);

// Injected into the application page only when you click "Fill this form". It fills empty fields
// it is sure about, attaches the tailored resume, highlights what it did, and never submits: you
// review the form and click the employer's Submit button yourself. CAPTCHAs are never touched.
(function (root) {
  "use strict";
  const M = root.HireFinchMatcher;
  const FILLED = "2px solid #10b981";
  const LEFT = "2px dashed #f59e0b";
  const esc = root.CSS && root.CSS.escape ? root.CSS.escape : (s) => String(s).replace(/["\\\]]/g, "\\$&");

  function visible(el) {
    if (el.disabled || el.readOnly || el.type === "hidden") return false;
    const style = root.getComputedStyle ? root.getComputedStyle(el) : null;
    if (style && (style.display === "none" || style.visibility === "hidden")) return false;
    return !el.closest("[aria-hidden='true'], .g-recaptcha, .h-captcha, [class*='captcha'], [id*='captcha']");
  }

  function textOf(node) {
    return node ? (node.innerText || node.textContent || "").replace(/\s+/g, " ").trim() : "";
  }

  /** The question a field asks: <label for>, wrapping label, aria, then nearby text. */
  function labelOf(el) {
    const doc = el.ownerDocument;
    if (el.id) {
      const lab = doc.querySelector(`label[for="${esc(el.id)}"]`);
      if (lab && textOf(lab)) return textOf(lab);
    }
    const wrap = el.closest("label");
    if (wrap && textOf(wrap)) return textOf(wrap);
    const by = el.getAttribute("aria-labelledby");
    if (by) {
      const t = by.split(/\s+/).map((id) => textOf(doc.getElementById(id))).join(" ").trim();
      if (t) return t;
    }
    if (el.getAttribute("aria-label")) return el.getAttribute("aria-label");
    const group = el.closest("fieldset");
    if (group && (el.type === "radio" || el.type === "checkbox")) {
      const legend = group.querySelector("legend");
      if (legend && textOf(legend)) return textOf(legend);
    }
    // Field wrappers used by Greenhouse, Lever and Ashby: the label text sits in the same block.
    const block = el.closest(".field, .application-question, .application-field, .form-group, [data-field], [class*='_field'], [class*='question']");
    if (block) {
      const lab = block.querySelector("label, .application-label, [class*='label']");
      if (lab && textOf(lab) && !lab.contains(el)) return textOf(lab);
    }
    // Otherwise the text just before the field, if it is short enough to be a label.
    const prev = (el.previousElementSibling && textOf(el.previousElementSibling)) || (el.parentElement && el.parentElement.previousElementSibling && textOf(el.parentElement.previousElementSibling));
    if (prev && prev.length <= 120) return prev;
    return el.placeholder || el.name || el.id || "";
  }

  /** The question of a radio group (its legend or group label), not the "Yes"/"No" next to one button. */
  function groupQuestion(el) {
    const set = el.closest("fieldset");
    if (set && set.querySelector("legend")) return textOf(set.querySelector("legend"));
    const group = el.closest("[role='radiogroup']");
    if (group) {
      const by = group.getAttribute("aria-labelledby");
      const t = group.getAttribute("aria-label") || (by && textOf(el.ownerDocument.getElementById(by)));
      if (t) return t;
    }
    // Outer question containers first (Lever: li.application-question > .application-label + .application-field).
    for (const sel of [".application-question", ".field", ".form-group", "[data-field]", "[class*='question']", ".application-field"]) {
      const block = el.closest(sel);
      if (!block) continue;
      const lab = block.querySelector(".application-label, legend, [class*='label']:not(label):not([class*='answer'])");
      if (lab && textOf(lab)) return textOf(lab);
      const prev = block.previousElementSibling;
      if (prev && textOf(prev) && textOf(prev).length <= 600) return textOf(prev);
    }
    return "";
  }

  function setValue(el, value) {
    const proto = el.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype : el.tagName === "SELECT" ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(proto, "value").set;
    setter.call(el, value); // the native setter, so React and Vue forms see the change
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
    el.dispatchEvent(new Event("blur", { bubbles: true }));
  }

  function mark(el, ok) {
    el.style.outline = ok ? FILLED : LEFT;
    el.style.outlineOffset = "2px";
  }

  function decide(label, data, numeric) {
    if (M.isNever(label)) return { skip: true };
    const key = M.classify(label);
    // What you wrote in Profile for a recurring question comes first: it is the most specific answer.
    const value = M.customAnswer(label, data.custom) ?? (key ? M.valueFor(key, label, data, { numeric }) : null);
    return { key, value: value ?? M.matchAnswer(label, data.answers) };
  }

  function attachResume(input, resume) {
    const bytes = Uint8Array.from(atob(resume.base64), (c) => c.charCodeAt(0));
    const file = new File([bytes], resume.filename, { type: resume.content_type });
    const dt = new DataTransfer();
    dt.items.add(file);
    input.files = dt.files;
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
  }

  function fill(data, doc) {
    doc = doc || root.document;
    const report = { filled: [], left: [], resume: false, resume_field: false, skipped_sensitive: 0 };
    const seenRadio = new Set();
    for (const el of doc.querySelectorAll("input, textarea, select")) {
      const type = (el.type || "").toLowerCase();
      if (["submit", "button", "reset", "image", "hidden", "password"].includes(type) || !visible(el)) continue;
      if (type === "checkbox") {
        // Only declaration boxes ("I certify…", privacy notice), and only when you allowed it in Profile.
        const text = labelOf(el);
        if (!el.checked && M.classify(text) === "declaration" && data.fields && data.fields.accept_declarations) {
          el.click();
          report.filled.push(text);
          mark(el, true);
        } else if (!el.checked && el.required) {
          report.left.push(text || el.name || "a required checkbox");
          mark(el, false);
        }
        continue;
      }
      const label = labelOf(el);
      if (type === "file") {
        const l = M.normalize(label + " " + (el.name || "") + " " + (el.id || ""));
        const isResume = /resume|\bcv\b|curriculum/.test(l) && !/cover/.test(l);
        if (isResume) report.resume_field = true;
        if (isResume && el.files && el.files.length) report.resume = true; // already attached
        if (data.resume && isResume && !(el.files && el.files.length)) {
          try {
            attachResume(el, data.resume);
            report.resume = true;
            mark(el, true);
          } catch (e) {
            report.left.push("Resume upload (attach it yourself)");
          }
        }
        continue;
      }
      if (type === "radio") {
        if (!el.name || seenRadio.has(el.name)) continue;
        seenRadio.add(el.name);
        const group = [...doc.querySelectorAll(`input[type=radio][name="${esc(el.name)}"]`)];
        const question = groupQuestion(el) || label;
        const { skip, value } = decide(question, data, false);
        if (skip) {
          report.skipped_sensitive++;
          continue;
        }
        if (group.some((r) => r.checked)) continue; // you already chose
        const i = value ? M.pickOption(group.map((r) => labelOf(r) || r.value), value) : -1;
        if (i >= 0) {
          group[i].click();
          report.filled.push(question);
          mark(group[i], true);
        } else if (group.some((r) => r.required)) {
          report.left.push(question);
          group.forEach((r) => mark(r, false));
        }
        continue;
      }
      if (el.value && String(el.value).trim()) continue; // never overwrite what is already there
      const { skip, key, value } = decide(label, data, type === "number");
      if (skip) {
        report.skipped_sensitive++;
        continue;
      }
      let done = false;
      if (value) {
        if (el.tagName === "SELECT") {
          const i = M.pickOption([...el.options].map((o) => o.text), value);
          if (i >= 0 && el.options[i].value !== "") {
            setValue(el, el.options[i].value);
            done = true;
          }
        } else if (!(type === "number" && Number.isNaN(Number(value)))) {
          setValue(el, value);
          done = true;
        }
      }
      if (done && el.tagName !== "SELECT" && String(el.value).trim() !== String(value).trim()) {
        done = false; // the page changed it back (e.g. a location typeahead): leave it to you
      }
      if (done) {
        report.filled.push(label || key);
        mark(el, true);
      } else if (el.required || el.getAttribute("aria-required") === "true") {
        report.left.push(label || el.name || "a required field");
        mark(el, false);
      }
    }
    return report;
  }

  root.__hireFinchFill = (data) => fill(data);
  root.HireFinchFill = { fill, labelOf };
})(typeof globalThis !== "undefined" ? globalThis : this);

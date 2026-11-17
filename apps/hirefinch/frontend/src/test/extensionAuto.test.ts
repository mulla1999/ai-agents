// Auto-apply's certainty checks and confirmation detection (extension/lib/auto.js).
import { beforeAll, describe, expect, it } from "vitest";
import "../../../extension/lib/auto.js";

const A = (globalThis as unknown as { HireFinchAuto: Record<string, (...a: unknown[]) => unknown> }).HireFinchAuto;
const READY = { filled: ["Email"], left: [], resume: true, resume_field: true };

beforeAll(() => {
  // jsdom has no layout: give elements a size unless they are display:none.
  Element.prototype.getBoundingClientRect = function () {
    const hidden = getComputedStyle(this as Element).display === "none";
    return { width: hidden ? 0 : 100, height: hidden ? 0 : 20, top: 0, left: 0, right: 100, bottom: 20, x: 0, y: 0, toJSON: () => ({}) } as DOMRect;
  };
});

function form(extra = "") {
  document.body.innerHTML = `<form><input style="outline: 2px solid rgb(16, 185, 129)" value="x"><button type="submit">Submit application</button>${extra}</form>`;
}

describe("auto-apply checks", () => {
  it("is ready only when nothing is left, the resume is attached and one Submit button exists", () => {
    form();
    expect(A.assess(READY, true)).toEqual({ ready: true, reasons: [] });
    expect((A.assess({ ...READY, left: ["Salary"] }, true) as { ready: boolean }).ready).toBe(false);
    expect((A.assess({ ...READY, resume: false }, true) as { reasons: string[] }).reasons).toContain("the resume could not be attached");
    form('<button type="submit">Apply now</button>');
    expect((A.assess(READY, true) as { reasons: string[] }).reasons).toContain("the Submit button could not be identified");
  });

  it("never submits with a CAPTCHA to solve, but allows the invisible reCAPTCHA badge", () => {
    form('<iframe src="https://www.google.com/recaptcha/api2/anchor?k=x&size=invisible" title="reCAPTCHA"></iframe>');
    expect(A.captchaShowing()).toBe(false);
    form('<iframe src="https://www.google.com/recaptcha/api2/anchor?k=x&size=normal" title="reCAPTCHA"></iframe>');
    expect(A.captchaShowing()).toBe(true);
    form('<div class="h-captcha"></div>');
    expect((A.assess(READY, true) as { reasons: string[] }).reasons).toContain("the form shows a CAPTCHA");
  });

  it("stops on a visible form error", () => {
    form('<p class="error">Please enter a valid phone number</p>');
    expect((A.assess(READY, true) as { ready: boolean }).ready).toBe(false);
  });

  it("recognises the employer's confirmation page", () => {
    document.body.innerHTML = "<h1>Thank you for applying to Acme!</h1><p>We have received your application and will be in touch.</p>";
    expect(A.confirmation()).toMatch(/Thank you for applying/);
    document.body.innerHTML = "<h1>Backend Engineer</h1><p>Apply for this job</p>";
    expect(A.confirmation()).toBeNull();
  });

  it("clicks the form's own Submit button", () => {
    form();
    let submitted = 0;
    document.querySelector("form")!.addEventListener("submit", (e) => {
      e.preventDefault();
      submitted++;
    });
    expect(A.clickSubmit()).toBe(true);
    expect(submitted).toBe(1);
  });
});

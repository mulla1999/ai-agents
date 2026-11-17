// The browser extension's form filler, against Greenhouse- and Lever-style markup.
import { beforeAll, describe, expect, it } from "vitest";
import "../../../extension/lib/matcher.js";
import "../../../extension/lib/fill.js";

type Report = { filled: string[]; left: string[]; resume: boolean; skipped_sensitive: number };
const g = globalThis as unknown as {
  HireFinchMatcher: { classify: (l: string) => string | null; pickOption: (t: string[], v: string) => number; valueFor: (k: string, l: string, d: unknown) => string | null };
  HireFinchFill: { fill: (d: unknown, doc?: Document) => Report };
};

const DATA = {
  fields: {
    full_name: "Riya Sharma", first_name: "Riya", last_name: "Sharma", email: "riya@example.com", phone: "+91 90000 00000",
    linkedin: "https://www.linkedin.com/in/riya", location: "Pune", notice_period_days: 60, expected_ctc_lpa: 20,
    authorized_to_work_in: ["India"], requires_sponsorship: false, current_company: "Initech",
  },
  answers: [{ question: "Why do you want to work at Acme?", answer: "Your payments platform matches my Kafka work." }],
  resume: { filename: "Riya_Sharma_Resume.pdf", content_type: "application/pdf", base64: btoa("%PDF-1.4 test") },
};

beforeAll(() => {
  // jsdom has no DataTransfer; a minimal stand-in so file inputs can be tested.
  class DT {
    items = { add: (f: File) => this.list.push(f) };
    list: File[] = [];
    get files() {
      const list = this.list;
      return Object.assign([...list], { item: (i: number) => list[i] }) as unknown as FileList;
    }
  }
  (globalThis as unknown as { DataTransfer: unknown }).DataTransfer = DT;
  // Browsers accept a DataTransfer's FileList on <input type=file>; jsdom only accepts its own type.
  const files = new WeakMap<HTMLInputElement, FileList>();
  Object.defineProperty(HTMLInputElement.prototype, "files", {
    configurable: true,
    get() {
      return files.get(this) ?? ([] as unknown as FileList);
    },
    set(v: FileList) {
      files.set(this, v);
    },
  });
});

describe("matcher", () => {
  it("classifies common labels and refuses sensitive ones", () => {
    const c = g.HireFinchMatcher.classify;
    expect(c("First Name*")).toBe("first_name");
    expect(c("LinkedIn Profile")).toBe("linkedin");
    expect(c("What is your notice period?")).toBe("notice_period");
    expect(c("Expected CTC (LPA)")).toBe("expected_ctc");
    expect(c("Will you now or in the future require visa sponsorship?")).toBe("sponsorship");
    expect(c("Gender")).toBe("gender"); // answered only from Profile → Self-identification
    expect(c("Are you a protected veteran?")).toBe("veteran");
    expect(c("What is your religion?")).toBeNull(); // never asked for, never answered
  });

  it("answers work authorisation only for the country it names", () => {
    const v = (label: string) => g.HireFinchMatcher.valueFor("work_authorization", label, DATA);
    expect(v("Are you legally authorized to work in India?")).toBe("Yes");
    expect(v("Are you legally authorized to work in the United States?")).toBe("No");
    expect(v("Are you authorized to work in the country of this job?")).toBeNull(); // unknown: left for you
  });

  it("never puts a profile value into a yes/no question, and avoids ambiguous money and skill-years", () => {
    const c = g.HireFinchMatcher.classify;
    expect(c("Are you subject to any employment agreements with your current employer?")).toBeNull();
    expect(c("Do you live in your current location?")).toBeNull();
    expect(c("Will you now or in the future require sponsorship for a visa?")).toBe("sponsorship"); // yes/no key: allowed
    expect(c("Total Years of experience")).toBe("years_experience");
    expect(c("Years of experience with Kafka")).toBeNull(); // per-skill years are not known
    const v = (label: string, numeric: boolean) => (g.HireFinchMatcher as any).valueFor("expected_ctc", label, DATA, { numeric });
    expect(v("Expected Compensation (Yearly)", true)).toBeNull(); // a bare 20 could mean ₹20
    expect(v("Expected CTC in LPA", true)).toBe("20");
    expect(v("Expected Compensation (Yearly)", false)).toBe("20 LPA");
  });

  it("fills ID-document name fields and your own answers from Profile", () => {
    const m = g.HireFinchMatcher as any;
    expect(m.classify("Name as per Aadhaar card")).toBe("full_name");
    expect(m.classify("Name as on Passport")).toBe("full_name");
    const custom = { nationality: "Indian", "shift": "Yes", "night shift": "No" };
    expect(m.customAnswer("Nationality*", custom)).toBe("Indian");
    expect(m.customAnswer("Are you OK with night shift?", custom)).toBe("No"); // longest keyword wins
    expect(m.customAnswer("Preferred Pronoun", custom)).toBeNull();
  });

  it("picks options by meaning", () => {
    const p = g.HireFinchMatcher.pickOption;
    expect(p(["Select…", "Yes", "No"], "No")).toBe(2);
    expect(p(["Immediate", "0-30 days", "31-60 days", "61-90 days"], "60")).toBe(2);
  });
});

describe("fill", () => {
  it("fills a Greenhouse-style form, attaches the resume, and leaves sensitive and unknown fields", () => {
    document.body.innerHTML = `
      <form id="application_form">
        <div class="field"><label for="first_name">First Name *</label><input id="first_name" required></div>
        <div class="field"><label for="last_name">Last Name *</label><input id="last_name" required></div>
        <div class="field"><label for="email">Email *</label><input id="email" type="email" required></div>
        <div class="field"><label for="phone">Phone</label><input id="phone" type="tel" value="already typed"></div>
        <div class="field"><label for="resume">Resume/CV *</label><input id="resume" type="file"></div>
        <div class="field"><label for="q1">LinkedIn Profile</label><input id="q1"></div>
        <div class="field"><label for="q2">Why do you want to work at Acme? *</label><textarea id="q2" required></textarea></div>
        <div class="field"><label for="q3">What is your notice period?</label>
          <select id="q3"><option value="">Select…</option><option value="a">0-30 days</option><option value="b">31-60 days</option></select></div>
        <fieldset><legend>Will you require visa sponsorship?</legend>
          <label><input type="radio" name="sp" value="1">Yes</label><label><input type="radio" name="sp" value="0">No</label></fieldset>
        <div class="field"><label for="g">Gender</label><select id="g"><option value="">Decline</option><option>Female</option></select></div>
        <div class="field"><label for="x">Favourite colour *</label><input id="x" required></div>
        <div class="g-recaptcha"><input id="captcha-token"></div>
        <button type="submit">Submit application</button>
      </form>`;
    let submitted = false;
    document.querySelector("form")!.addEventListener("submit", () => (submitted = true));
    const report = g.HireFinchFill.fill(DATA, document);

    const val = (id: string) => (document.getElementById(id) as HTMLInputElement).value;
    expect(val("first_name")).toBe("Riya");
    expect(val("last_name")).toBe("Sharma");
    expect(val("email")).toBe("riya@example.com");
    expect(val("phone")).toBe("already typed"); // never overwrites
    expect(val("q1")).toBe("https://www.linkedin.com/in/riya");
    expect(val("q2")).toContain("payments platform");
    expect(val("q3")).toBe("b"); // 60 days → 31-60
    expect((document.querySelector("input[name=sp][value='0']") as HTMLInputElement).checked).toBe(true);
    expect(val("g")).toBe(""); // gender left alone: not set in Profile
    expect(val("captcha-token")).toBe(""); // CAPTCHA untouched
    expect(report.resume).toBe(true);
    expect((document.getElementById("resume") as HTMLInputElement).files![0].name).toBe("Riya_Sharma_Resume.pdf");
    expect(report.left).toContain("Favourite colour *");
    expect(report.left).not.toContain("Gender");
    expect(submitted).toBe(false); // it never submits
  });

  it("answers self-identification only from Profile, declines when asked to, and ticks declarations only if allowed", () => {
    document.body.innerHTML = `
      <form>
        <div class="field"><label for="g">Gender</label><select id="g"><option value="">Select</option><option value="m">Male</option><option value="f">Female</option><option value="d">I don't wish to answer</option></select></div>
        <div class="field"><label for="w">Have you previously worked at or consulted for Initech?</label><select id="w"><option value="">Select</option><option>Yes</option><option>No</option></select></div>
        <div class="field"><label for="b">Are you based out of Bangalore?</label><select id="b"><option value="">Select</option><option>Yes</option><option>No</option></select></div>
        <label><input type="checkbox" id="c" required> I certify that the information I have provided is accurate</label>
      </form>`;
    const data = { ...DATA, fields: { ...DATA.fields, location: "Bengaluru, Karnataka", employers: ["Initech Pvt. Ltd."], job_company: "Initech",
      self_id: { gender: "Prefer not to say" }, accept_declarations: true } };
    g.HireFinchFill.fill(data, document);
    const v = (id: string) => (document.getElementById(id) as HTMLSelectElement).value;
    expect(v("g")).toBe("d");
    expect(v("w")).toBe("Yes"); // from the employers on your resume
    expect(v("b")).toBe("Yes"); // Bangalore = Bengaluru
    expect((document.getElementById("c") as HTMLInputElement).checked).toBe(true);

    document.body.innerHTML = `<form><label><input type="checkbox" id="c2" required> I certify that the information is accurate</label></form>`;
    const report = g.HireFinchFill.fill({ ...DATA, fields: { ...DATA.fields, accept_declarations: false } }, document);
    expect((document.getElementById("c2") as HTMLInputElement).checked).toBe(false);
    expect(report.left[0]).toMatch(/I certify/);
  });

  it("fills a Lever-style form by name and label", () => {
    document.body.innerHTML = `
      <form>
        <ul><li class="application-question"><div class="application-label">Full name</div><input name="name"></li>
        <li class="application-question"><div class="application-label">Current company</div><input name="org"></li>
        <li class="application-question"><div class="application-label">LinkedIn URL</div><input name="urls[LinkedIn]"></li></ul>
      </form>`;
    const report = g.HireFinchFill.fill(DATA, document);
    const val = (name: string) => (document.querySelector(`[name="${name}"]`) as HTMLInputElement).value;
    expect(val("name")).toBe("Riya Sharma");
    expect(val("org")).toBe("Initech");
    expect(val("urls[LinkedIn]")).toBe("https://www.linkedin.com/in/riya");
    expect(report.filled).toHaveLength(3);
  });
});

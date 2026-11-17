// Decides what goes into a form field, from its label. Pure functions, no DOM: shared by fill.js
// (injected into the page) and the tests. Loaded as a classic script, so it sets a global.
(function (root) {
  "use strict";

  // Never filled, whatever the label says. Gender, ethnicity, disability, veteran status and
  // declarations are answered only from what you set in Profile (see self_id and the rules below).
  const NEVER = /\b(sexual orientation|religio|caste|marital|\bage\b|signature|captcha|cover letter|password)/i;

  // A yes/no question ("Are you subject to agreements with your current employer?") never gets a
  // profile value such as a company name; only the yes/no keys below may answer it.
  const YES_NO = /^(are|do|does|did|have|has|had|will|would|is|was|were|can|could|should|may)\b/;
  const YES_NO_KEYS = new Set(["sponsorship", "relocate", "work_authorization", "previously_worked", "based_in", "managed_team",
    "background_check", "criminal_record", "declaration", "onsite", "disability", "veteran"]);

  const RULES = [
    ["gender", /\bgender\b|^sex$/],
    ["pronouns", /\bpronoun/],
    ["ethnicity", /\b(race|ethnicity|ethnic)\b/],
    ["disability", /\bdisab/],
    ["veteran", /\bveteran/],
    ["date_of_birth", /\bdate of birth\b|\bbirth ?date\b|\bdob\b/],
    ["criminal_record", /\b(convicted|criminal (record|offen[cs]e|history))\b/],
    ["background_check", /\bbackground (check|verification|screening)\b/],
    ["declaration", /\bi (hereby )?(certify|declare|confirm|acknowledge|agree|consent)\b|\bprivacy (policy|notice)\b|\bterms (and|&) conditions\b/],
    ["previously_worked", /\b(previously|ever|before) (worked|been employed|consulted)\b|\bformer employee\b|\b(worked|consulted) (at|for) .{2,60} (before|previously)\b/],
    ["based_in", /\bare you (currently )?(based|located|living|residing) (in|out of|at|near)\b/],
    ["country_of_residence", /\bcountry of residence\b|\bcurrent country\b|\bwhich country (are|do) you\b/],
    ["managed_team", /\b(managing|managed|lead(ing)?|led) (a )?(team|people)\b|\bpeople management\b/],
    ["highest_education", /\bhighest (level of )?(education|qualification|degree)\b|\beducation(al)? (level|qualification)\b/],
    ["how_heard", /\bhow did you (hear|find|learn|come across)\b/],
    ["onsite", /\b(work|working) (from|in) (the )?office\b|\bon-?site\b.*\b(ok|okay|comfortable|willing|able)\b/],
    ["linkedin", /linked\s*in/],
    ["github", /git\s*hub/],
    ["email", /e-?mail/],
    ["phone", /\b(phone|mobile|cell|contact number|telephone|whatsapp)\b/],
    ["first_name", /\b(first|given)\s*name\b|^fname$/],
    ["last_name", /\b(last|family|sur)\s*name\b|^surname$|^lname$/],
    // "Name as per Aadhaar card", "Name as on passport": the full name, which you check before submitting.
    ["full_name", /^(full\s*)?name\*?$|\b(full|legal|your|candidate'?s?)\s+name\b|^(full\s+)?name (as )?(per|on|in)\b/],
    ["current_title", /\bcurrent\s+(job\s+)?(title|role|position|designation)\b/],
    ["current_company", /\b(current|present|latest|most recent)\s+(company|employer|organi[sz]ation)\b|^(company|organi[sz]ation|org)$/],
    ["years_experience", /\b(total\s+)?(years|yrs)\s+(of\s+)?(total\s+|professional\s+|relevant\s+|work\s+)?experience\b(?!\s+(in|with|using|on|of)\s+\w)|\bexperience\s*\(?in years\)?$|^total experience$/],
    ["notice_period", /\bnotice\s*period\b|how soon can you (join|start)|\b(joining|start) (date|time)\b|earliest (start|joining)/],
    ["expected_ctc", /\b(expected|desired|target)\s+(ctc|salary|compensation|pay|package)\b|salary expectation|expected annual/],
    ["current_ctc", /\b(current|present|existing)\s+(ctc|salary|compensation|pay|package)\b/],
    ["sponsorship", /\bsponsor/],
    ["relocate", /\brelocat/],
    ["work_authorization", /authori[sz]ed to work|legally (allowed|eligible|able) to work|right to work|work (permit|authori[sz]ation)|eligible to work/],
    ["location", /\b(current\s+)?(location|city)\b|where (are you|do you) (based|live|located)/],
    ["portfolio", /\b(portfolio|personal (website|site)|website|blog|other (link|url|website))\b/],
  ];

  const COUNTRIES = ["india", "united states", "usa", "us", "united kingdom", "uk", "canada", "germany", "singapore",
    "australia", "netherlands", "ireland", "france", "uae", "japan"];
  const ALIAS = { usa: "united states", us: "united states", uk: "united kingdom" };

  const CITY = { bangalore: "bengaluru", bombay: "mumbai", gurgaon: "gurugram", madras: "chennai", calcutta: "kolkata" };
  function companyKey(name) {
    return normalize(name).replace(/\b(pvt|private|ltd|limited|inc|llc|llp|corp|corporation|co|technologies|technology|solutions|software|labs|india)\b/g, "").replace(/\s+/g, " ").trim();
  }

  function normalize(text) {
    return String(text || "").toLowerCase().replace(/[*:?()\[\]]/g, " ").replace(/\s+/g, " ").trim();
  }

  function classify(label) {
    const text = normalize(label);
    if (!text || NEVER.test(text)) return null;
    for (const [key, pattern] of RULES) {
      if (pattern.test(text)) return YES_NO.test(text) && !YES_NO_KEYS.has(key) ? null : key;
    }
    return null;
  }

  function isNever(label) {
    return NEVER.test(normalize(label));
  }

  const STOP = new Set("a an the of to for in on and or your you are is do have what please with this that".split(" "));
  function tokens(text) {
    return new Set(normalize(text).split(/[^a-z0-9+#]+/).filter((w) => w.length > 1 && !STOP.has(w)));
  }

  /** A prepared answer whose question matches the label closely enough (word overlap). */
  function matchAnswer(label, answers) {
    const want = tokens(label);
    if (!want.size) return null;
    let best = null;
    let bestScore = 0;
    for (const a of answers || []) {
      const have = tokens(a.question);
      const shared = [...want].filter((w) => have.has(w)).length;
      const score = shared / new Set([...want, ...have]).size;
      if (score > bestScore) [best, bestScore] = [a, score];
    }
    return bestScore >= 0.6 ? best.answer : null;
  }

  /** Your own answer from Profile ("nationality = Indian") whose keyword is in the label; the longest keyword wins. */
  function customAnswer(label, custom) {
    const text = ` ${normalize(label)} `;
    let best = null;
    for (const [key, answer] of Object.entries(custom || {})) {
      const k = normalize(key);
      if (k && String(answer || "").trim() && text.includes(` ${k}`) && (!best || k.length > best[0].length)) best = [k, String(answer).trim()];
    }
    return best ? best[1] : null;
  }

  function yesNo(value) {
    return value === true ? "Yes" : value === false ? "No" : null;
  }

  /** The value for a field key, as text, or null when the agent does not know it (leave it for you). */
  function valueFor(key, label, data, { numeric = false } = {}) {
    const f = (data && data.fields) || {};
    switch (key) {
      case "notice_period":
        if (f.notice_period_days == null) return null;
        return numeric ? String(f.notice_period_days) : `${f.notice_period_days} days`;
      case "current_ctc":
      case "expected_ctc": {
        const v = f[key + "_lpa"];
        if (v == null) return null;
        // A bare number is ambiguous (20 could be read as ₹20): only when the field asks in lakhs.
        if (numeric) return /\b(lpa|lakhs?|lacs?)\b/.test(normalize(label)) ? String(v) : null;
        return `${v} LPA`;
      }
      case "years_experience":
        return f.years_experience == null ? null : String(f.years_experience);
      case "sponsorship":
        return yesNo(f.requires_sponsorship);
      case "gender":
      case "pronouns":
      case "ethnicity":
      case "disability":
      case "veteran":
      case "date_of_birth":
        return (f.self_id && f.self_id[key]) || null; // only what you wrote in Profile
      case "criminal_record":
        return yesNo(f.criminal_record);
      case "background_check":
        return yesNo(f.background_check_consent);
      case "declaration":
        return f.accept_declarations ? "Yes" : null;
      case "managed_team":
        return yesNo(f.managed_team);
      case "onsite":
        return yesNo(f.willing_onsite);
      case "how_heard":
        return f.how_did_you_hear || null;
      case "previously_worked": {
        if (!f.job_company) return null;
        const here = companyKey(f.job_company);
        return (f.employers || []).some((e) => { const m = companyKey(e); return here && m && (m.includes(here) || here.includes(m)); }) ? "Yes" : "No";
      }
      case "based_in": {
        if (!f.location) return null;
        const where = normalize(label).split(/\b(?:in|out of|at|near)\b/).pop().split(",")[0].replace(/[✱]/g, "").trim();
        if (!where) return null;
        const city = (t) => CITY[t] || t;
        return normalize(f.location).split(/[,/]/).map((x) => city(x.trim())).includes(city(where)) ? "Yes" : "No";
      }
      case "relocate":
        return yesNo(f.willing_to_relocate);
      case "work_authorization": {
        const allowed = (f.authorized_to_work_in || []).map((c) => normalize(c));
        if (!allowed.length) return null;
        const text = ` ${normalize(label)} `;
        const named = COUNTRIES.filter((c) => text.includes(` ${c} `)).map((c) => ALIAS[c] || c);
        if (!named.length) return null; // which country? leave it for you
        return named.some((c) => allowed.includes(c)) ? "Yes" : "No";
      }
      default: {
        const v = f[key];
        return v == null || v === "" ? null : String(v);
      }
    }
  }

  const DECLINE = /\b(prefer not|decline|don'?t wish|do not wish|not to (say|disclose|answer)|rather not|choose not)\b/;

  /** Index of the <option>/radio text that fits a value ("Yes", "30 days", "India"), or -1. */
  function pickOption(texts, value) {
    const want = normalize(value);
    if (!want) return -1;
    const norm = texts.map(normalize);
    if (DECLINE.test(want)) return norm.findIndex((t) => DECLINE.test(t)); // "Prefer not to say" ↔ "I don't wish to answer"
    let i = norm.findIndex((t) => t === want);
    if (i >= 0) return i;
    if (want === "yes" || want === "no") return norm.findIndex((t) => t.startsWith(want));
    const num = parseFloat(want);
    if (!Number.isNaN(num)) {
      // "30 days" against ranges like "0-30 days", "31-60 days", "Immediate"
      i = norm.findIndex((t) => {
        const m = t.match(/(\d+)\s*(?:-|to)\s*(\d+)/);
        return m && num >= Number(m[1]) && num <= Number(m[2]);
      });
      if (i >= 0) return i;
    }
    return norm.findIndex((t) => t && (t.includes(want) || want.includes(t)) && t.length > 1);
  }

  const api = { classify, isNever, matchAnswer, customAnswer, valueFor, pickOption, normalize };
  root.HireFinchMatcher = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof globalThis !== "undefined" ? globalThis : this);

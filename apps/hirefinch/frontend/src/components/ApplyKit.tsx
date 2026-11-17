// For jobs applied to on the employer's own site (Greenhouse, Lever, Ashby, LinkedIn, Naukri…). Those
// sites give candidates no submission API and protect their forms against bots, so the agent prepares
// everything and you submit: download the tailored resume, copy each field, open the form, record it.

import { useQuery } from "@tanstack/react-query";
import { Check, Copy, Download, ExternalLink } from "lucide-react";
import { useState } from "react";
import { api } from "../api/client";
import type { Application, ProfileResponse } from "../api/types";
import { isPhone } from "./ExtensionKeys";
import { cx } from "./ui";

const MAX_LPA = 500; // the same rule as the server: larger values are rupees typed into an LPA field

function CopyRow({ label, value }: { label: string; value: string | null | undefined }) {
  const [done, setDone] = useState(false);
  const usable = !!value && value !== "••••";
  return (
    <li className="flex items-center gap-2 rounded-lg px-2 py-1.5 text-sm hover:bg-slate-50">
      {/* Phones: label above the value, so long answers stay readable next to a thumb-sized button. */}
      <div className="flex min-w-0 flex-1 flex-col sm:flex-row sm:items-center sm:gap-2">
        <span className="truncate text-xs text-slate-500 sm:w-40 sm:shrink-0 sm:text-sm" title={label}>
          {label}
        </span>
        <span className={cx("min-w-0 flex-1 line-clamp-2 sm:line-clamp-1", usable ? "text-slate-900" : "text-slate-400")} title={usable ? value! : undefined}>
          {usable ? value : value === "••••" ? "hidden: see Profile" : "not set"}
        </span>
      </div>
      <button
        type="button"
        disabled={!usable}
        aria-label={`Copy ${label}`}
        onClick={async () => {
          try {
            await navigator.clipboard.writeText(value!);
            setDone(true);
            setTimeout(() => setDone(false), 1500);
          } catch {
            /* clipboard blocked: the value is visible to copy by hand */
          }
        }}
        className="grid size-10 shrink-0 place-items-center sm:size-7 rounded-md text-slate-500 transition hover:bg-indigo-50 hover:text-indigo-700 disabled:opacity-30"
      >
        {done ? <Check className="size-4 text-emerald-600" /> : <Copy className="size-4" />}
      </button>
    </li>
  );
}

function AutoApply({ app }: { app: Application }) {
  const [state, setState] = useState<"idle" | "busy" | "opened" | string>("idle");
  return (
    <div className="mb-4 rounded-lg border border-indigo-200 bg-white p-3">
      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          disabled={state === "busy"}
          onClick={async () => {
            // Open the tab now (inside the click) so the browser does not block it, then point it at the form.
            const tab = window.open("about:blank", "_blank");
            setState("busy");
            try {
              const r = await api<{ url: string }>(`/applications/${app.id}/auto-apply`, { method: "POST" });
              if (tab) {
                tab.opener = null;
                tab.location.href = r.url;
              } else window.location.href = r.url;
              setState("opened");
            } catch (e) {
              tab?.close();
              setState((e as Error).message);
            }
          }}
          className="inline-flex items-center gap-1.5 rounded-lg bg-gradient-to-b from-emerald-500 to-emerald-600 px-3.5 py-2 text-sm font-medium text-white shadow-sm hover:to-emerald-700 disabled:opacity-60"
        >
          Auto-apply with the extension
        </button>
        <span className="text-xs text-slate-600">
          Opens {app.company}'s form; the extension fills it and submits only if every required field is filled and no CAPTCHA shows, after a 5-second countdown. You get an email once {app.company} confirms.
        </span>
      </div>
      {state === "opened" && <p className="mt-2 text-xs text-emerald-700">Opened in a new tab. Watch it there: it stops and tells you if anything needs you.</p>}
      {state !== "idle" && state !== "busy" && state !== "opened" && <p className="mt-2 text-xs text-red-600">{state}</p>}
    </div>
  );
}

export function ApplyKit({ app, applyLink }: { app: Application; applyLink: string }) {
  const profile = useQuery({ queryKey: ["profile"], queryFn: () => api<ProfileResponse>("/profile"), staleTime: 60_000 });
  const p = profile.data?.profile;
  const lpa = (v: number | null | undefined) => (v != null && v > 0 && v <= MAX_LPA ? `${v} LPA` : null);
  const fields: [string, string | null | undefined][] = [
    ["Full name", p?.full_name],
    ["Email", p?.contact_email],
    ["Phone", p?.phone],
    ["Location", p?.location],
    ["LinkedIn", p?.linkedin_url],
    ["Portfolio / GitHub", p?.portfolio_url],
    ["Notice period", p?.notice_period_days != null ? `${p.notice_period_days} days` : null],
    ["Current CTC", lpa(p?.current_ctc_lpa)],
    ["Expected CTC", lpa(p?.expected_ctc_lpa)],
    ["Authorised to work in", p?.authorized_to_work_in?.join(", ")],
  ];
  const answered = app.answers.filter((a) => !a.needs_user && a.answer);
  const resume = app.resume_version_id ? `/api/resumes/versions/${app.resume_version_id}/download` : null;
  const phone = isPhone(); // phone browsers can't run the extension: copy and paste instead

  return (
    <section className="mt-4 rounded-xl border border-indigo-100 bg-indigo-50/40 p-4">
      <h3 className="text-sm font-semibold text-slate-900">Apply kit</h3>
      <p className="mb-3 text-xs text-slate-600">
        {app.company} takes applications on its own site, which does not allow automated submission. Everything is ready: it takes about a minute.{" "}
        {phone ? (
          <>Download the resume, tap the copy buttons, and paste each value into {app.company}'s form.</>
        ) : (
          <>
            With the{" "}
            <a href="/account" className="font-medium text-indigo-700 hover:underline">
              browser extension
            </a>
            , the form fills itself and you just review and submit.
          </>
        )}
      </p>
      {!phone && <AutoApply app={app} />}
      {!phone && <p className="mb-2 text-xs font-medium text-slate-500">Or do it yourself:</p>}
      <ol className="space-y-3 text-sm">
        <li>
          <span className="font-medium text-slate-800">1. Download your resume tailored for this job</span>
          <div className="mt-1.5 flex gap-2">
            {resume ? (
              <>
                <a href={`${resume}?format=pdf`} className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50">
                  <Download className="size-3.5" aria-hidden /> PDF
                </a>
                <a href={`${resume}?format=docx`} className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50">
                  <Download className="size-3.5" aria-hidden /> DOCX
                </a>
              </>
            ) : (
              <span className="text-xs text-slate-500">No tailored resume yet.</span>
            )}
          </div>
        </li>
        <li>
          <span className="font-medium text-slate-800">2. Copy what the form asks</span>
          {phone && <p className="text-xs text-slate-500">Tip: open the form in another tab (step 3), then switch back here to copy each value.</p>}
          <ul className="mt-1.5 rounded-lg border border-slate-200 bg-white p-1">
            {fields.map(([label, value]) => (
              <CopyRow key={label} label={label} value={value} />
            ))}
            {answered.map((a) => (
              <CopyRow key={a.id} label={a.question} value={a.answer} />
            ))}
          </ul>
        </li>
        <li>
          <span className="font-medium text-slate-800">3. Open the application and submit it</span>
          <div className="mt-1.5">
            <a href={applyLink} target="_blank" rel="noopener noreferrer nofollow" className="inline-flex items-center gap-1.5 rounded-lg bg-gradient-to-b from-indigo-500 to-indigo-600 px-3.5 py-2 text-xs font-medium text-white shadow-sm hover:to-indigo-700">
              Open {app.company}'s application <ExternalLink className="size-3.5" aria-hidden />
            </a>
          </div>
        </li>
        <li className="font-medium text-slate-800">4. Come back and tap “I applied”, with the confirmation number if you get one</li>
      </ol>
    </section>
  );
}

import { useQuery } from "@tanstack/react-query";
import { Download } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import { api, qs } from "../api/client";
import { JOB_STATUSES, type Application } from "../api/types";
import { Badge, Card, Empty, ErrorText, Field, JsonView, Loading, PageHeader, Select, StatusBadge, cx, formatDate, outcomeTone, statusLabel } from "../components/ui";
import { AttemptTable } from "./Queue";

const OUTCOME_TEXT: Record<string, string> = { pending: "not sent yet", confirmed: "confirmed received", uncertain: "sent, not confirmed", failed: "failed" };

type View = "sent" | "waiting" | "all";
const sent = (a: Application) => !!a.submitted_at || a.outcome !== "pending";

export function TrackerPage() {
  const [status, setStatus] = useState("");
  const [view, setView] = useState<View>("sent");
  const [open, setOpen] = useState<number | null>(null);
  const query = useQuery({ queryKey: ["tracker", status], queryFn: () => api<Application[]>(`/applications${qs({ status })}`) });
  const all = query.data ?? [];
  const counts = {
    sent: all.filter(sent).length,
    interviewing: all.filter((a) => a.job_status === "interview_scheduled").length,
    rejected: all.filter((a) => a.job_status === "rejected").length,
    waiting: all.filter((a) => !sent(a)).length,
  };
  const shown = all.filter((a) => (view === "all" ? true : view === "sent" ? sent(a) : !sent(a)));
  const VIEWS: [View, string][] = [
    ["sent", `Applied (${counts.sent})`],
    ["waiting", `Not sent yet (${counts.waiting})`],
    ["all", `All (${all.length})`],
  ];
  return (
    <>
      <PageHeader
        title="Application Tracker"
        subtitle="Every job you applied to and what happened next."
        actions={
          <a href="/api/applications/export.csv" className="inline-flex items-center gap-1.5 rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm hover:bg-slate-50">
            <Download className="size-4" aria-hidden /> Export CSV
          </a>
        }
      />
      {all.length > 0 && (
        <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
          {(
            [
              ["Applied", counts.sent, "text-indigo-700"],
              ["Interviewing", counts.interviewing, "text-emerald-700"],
              ["Rejected", counts.rejected, "text-slate-700"],
              ["Not sent yet", counts.waiting, "text-amber-700"],
            ] as const
          ).map(([label, n, tone]) => (
            <div key={label} className="rounded-2xl border border-slate-200/80 bg-white px-4 py-3 shadow-soft">
              <div className={cx("text-2xl font-semibold tabular-nums", tone)}>{n}</div>
              <div className="text-sm text-slate-600">{label}</div>
            </div>
          ))}
        </div>
      )}
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <div className="flex gap-1.5 overflow-x-auto" role="group" aria-label="Show">
          {VIEWS.map(([key, label]) => (
            <button
              key={key}
              type="button"
              aria-pressed={view === key}
              onClick={() => setView(key)}
              className={cx(
                "shrink-0 rounded-full px-3 py-1.5 text-sm ring-1 ring-inset transition",
                view === key ? "bg-indigo-600 text-white ring-indigo-600" : "bg-white text-slate-700 ring-slate-200 hover:bg-slate-50",
              )}
            >
              {label}
            </button>
          ))}
        </div>
        <div className="w-full sm:ml-auto sm:w-56">
          <Field label="Job status">
            <Select value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="">Any</option>
              {JOB_STATUSES.map((s) => (
                <option key={s} value={s}>
                  {statusLabel(s)}
                </option>
              ))}
            </Select>
          </Field>
        </div>
      </div>
      {view === "waiting" && counts.waiting > 0 && (
        <p className="mb-3 text-sm text-slate-600">
          These are prepared but not sent. Finish them in the{" "}
          <Link className="text-indigo-700 hover:underline" to="/queue">
            Application Queue
          </Link>
          .
        </p>
      )}
      {query.isLoading ? (
        <Loading />
      ) : query.error ? (
        <ErrorText error={query.error} />
      ) : shown.length === 0 ? (
        <Card>
          <Empty>{view === "sent" ? "You haven't applied anywhere yet. Applications you send show up here." : "Nothing here."}</Empty>
        </Card>
      ) : (
        <ul className="grid gap-3 md:grid-cols-2">
          {shown.map((a) => (
            <li key={a.id} className="min-w-0 rounded-2xl border border-slate-200/80 bg-white p-4 shadow-soft">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <Link className="font-medium leading-snug text-indigo-700 hover:underline" to={`/jobs/${a.job_id}`}>
                    {a.job_title}
                  </Link>
                  <div className="truncate text-sm text-slate-600">{a.company}</div>
                </div>
                <StatusBadge status={a.job_status} />
              </div>
              <dl className="mt-3 grid grid-cols-2 gap-x-3 gap-y-1.5 text-sm">
                <dt className="text-slate-500">Applied</dt>
                <dd>
                  {sent(a) ? (
                    <>
                      {a.submitted_at ? `${formatDate(a.submitted_at)} · ` : ""}
                      <Badge tone={outcomeTone(a.outcome)}>{OUTCOME_TEXT[a.outcome] ?? a.outcome}</Badge>
                    </>
                  ) : (
                    <Link className="text-indigo-700 hover:underline" to={`/queue?job=${a.job_id}`}>
                      Not sent yet: finish it →
                    </Link>
                  )}
                </dd>
                <dt className="text-slate-500">How</dt>
                <dd>{a.route === "email" ? "by email" : a.route === "manual" ? "on the employer's site" : a.route}</dd>
                {a.confirmation_ref && (
                  <>
                    <dt className="text-slate-500">Reference</dt>
                    <dd className="break-all">{a.confirmation_ref}</dd>
                  </>
                )}
              </dl>
              <div className="mt-3 flex flex-wrap items-center gap-3 border-t border-slate-100 pt-2 text-sm">
                {a.resume_version_id && (
                  <Link className="text-indigo-700 hover:underline" to={`/resumes/${a.resume_version_id}`}>
                    {sent(a) ? "Resume sent" : "Tailored resume"}
                  </Link>
                )}
                {a.job_status === "interview_scheduled" && (
                  <Link className="font-medium text-emerald-700 hover:underline" to={`/jobs/${a.job_id}#interview`}>
                    Prepare for the interview
                  </Link>
                )}
                <button type="button" aria-expanded={open === a.id} onClick={() => setOpen(open === a.id ? null : a.id)} className="ml-auto text-slate-600 hover:text-indigo-700">
                  {open === a.id ? "Hide details" : "Details"}
                </button>
              </div>
              {open === a.id && (
                <div className="mt-2 space-y-2 rounded-xl bg-slate-50 p-3">
                  <h3 className="text-xs font-semibold uppercase text-slate-500">Attempts</h3>
                  {a.attempts.length ? <div className="overflow-x-auto"><AttemptTable app={a} /></div> : <p className="text-sm text-slate-500">Not sent yet.</p>}
                  <details className="text-xs text-slate-500">
                    <summary className="cursor-pointer">Technical details</summary>
                    <JsonView value={a.evidence} />
                    {a.submitted_file_sha256 && <p className="mt-1 break-all">File checksum {a.submitted_file_sha256}</p>}
                  </details>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

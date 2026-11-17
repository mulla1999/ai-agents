import { useQuery } from "@tanstack/react-query";
import { ChevronDown, ExternalLink, Search } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router";
import { api } from "../api/client";
import { ApplyKit } from "../components/ApplyKit";
import type { Answer, Application, Queue } from "../api/types";
import {
  Alert,
  Badge,
  Button,
  Card,
  Empty,
  ErrorText,
  Field,
  List,
  Loading,
  PageHeader,
  StatusBadge,
  cx,
  TextArea,
  TextInput,
  formatDate,
  outcomeTone,
  useAction,
} from "../components/ui";

type QueueFilter = "all" | "needs_you" | "manual" | "email";
const FILTERS: [QueueFilter, string][] = [
  ["all", "All"],
  ["needs_you", "Needs you"],
  ["manual", "Apply on site"],
  ["email", "By email"],
];
const PAGE = 20;

function needsYou(a: Application) {
  return (a.approval_blockers ?? []).length > 0 || a.answers.some((x) => x.needs_user) || ["needs_manual", "application_failed"].includes(a.job_status);
}

export function QueuePage() {
  const query = useQuery({ queryKey: ["queue"], queryFn: () => api<Queue>("/applications/queue") });
  const prepare = useAction((jobId: number) => api(`/jobs/${jobId}/application`, { method: "POST" }));
  const [params, setParams] = useSearchParams();
  const [text, setText] = useState("");
  const [filter, setFilter] = useState<QueueFilter>("all");
  const [shown, setShown] = useState(PAGE);
  // ?job=<id> (from a job page's Apply button) opens that application.
  const openJob = Number(params.get("job")) || null;
  const [openId, setOpenId] = useState<number | null>(null);
  useEffect(() => {
    const match = openJob && query.data?.applications.find((a) => a.job_id === openJob);
    if (match) setOpenId(match.id);
  }, [openJob, query.data]);
  if (query.isLoading) return <Loading />;
  if (query.error) return <ErrorText error={query.error} />;
  const q = query.data!;
  const outreachApprovals = q.approvals.filter((a) => a.kind === "outreach");
  const needle = text.trim().toLowerCase();
  const visible = q.applications.filter(
    (a) =>
      (!needle || `${a.job_title} ${a.company}`.toLowerCase().includes(needle)) &&
      (filter === "all" || (filter === "needs_you" ? needsYou(a) : a.route === filter)),
  );
  const toggle = (id: number) => {
    setOpenId(openId === id ? null : id);
    if (params.has("job")) setParams({}, { replace: true });
  };
  return (
    <>
      <PageHeader title="Application Queue" subtitle="Applications ready for you. Open one to see the tailored resume, the prepared answers and the next step." />
      <div className="space-y-4">
        {q.resume_ready_jobs.length > 0 && (
          <Card title="Resumes ready: prepare the application">
            <ul className="space-y-2 text-sm">
              {q.resume_ready_jobs.map((j) => (
                <li key={j.id} className="flex items-center justify-between gap-2">
                  <Link className="text-indigo-700 hover:underline" to={`/jobs/${j.id}`}>
                    {j.title} · {j.company}
                  </Link>
                  <Button busy={prepare.isPending && prepare.variables === j.id} onClick={() => prepare.mutate(j.id)}>
                    Prepare application
                  </Button>
                </li>
              ))}
            </ul>
            <ErrorText error={prepare.error} />
          </Card>
        )}
        {outreachApprovals.length > 0 && (
          <Alert tone="info">
            {outreachApprovals.length} recruiter email{outreachApprovals.length > 1 ? "s" : ""} waiting for review in{" "}
            <Link className="underline" to="/outreach">
              Recruiter Outreach
            </Link>
            .
          </Alert>
        )}
        {q.applications.length === 0 ? (
          <Card>
            <Empty>Nothing waiting. Applications appear here once a resume is tailored for a job you chose to apply to.</Empty>
          </Card>
        ) : (
          <>
            <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
              <label className="relative min-w-0 flex-1">
                <span className="sr-only">Search applications</span>
                <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-slate-400" aria-hidden />
                <input
                  value={text}
                  onChange={(e) => setText(e.target.value)}
                  placeholder="Search by job or company"
                  className="w-full rounded-xl border border-slate-200 bg-white py-2.5 pl-9 pr-3 text-sm focus:border-indigo-400 focus:outline-none focus:ring-4 focus:ring-indigo-100"
                />
              </label>
              <div className="flex gap-1.5 overflow-x-auto pb-1 sm:pb-0" role="group" aria-label="Filter">
                {FILTERS.map(([key, label]) => (
                  <button
                    key={key}
                    type="button"
                    aria-pressed={filter === key}
                    onClick={() => setFilter(key)}
                    className={cx(
                      "shrink-0 rounded-full px-3 py-1.5 text-sm ring-1 ring-inset transition",
                      filter === key ? "bg-indigo-600 text-white ring-indigo-600" : "bg-white text-slate-700 ring-slate-200 hover:bg-slate-50",
                    )}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>
            <p className="px-1 text-sm text-slate-500">
              {visible.length === q.applications.length ? `${visible.length} applications` : `${visible.length} of ${q.applications.length} applications`}
            </p>
            {visible.length === 0 && (
              <Card>
                <Empty>No applications match.</Empty>
              </Card>
            )}
            {visible.slice(0, shown).map((a) => (
              <ApplicationCard key={a.id} app={a} open={openId === a.id} onToggle={() => toggle(a.id)} />
            ))}
            {visible.length > shown && (
              <Button className="w-full" onClick={() => setShown(shown + PAGE)}>
                Show more ({visible.length - shown} left)
              </Button>
            )}
          </>
        )}
      </div>
    </>
  );
}

const ROUTE_LABELS: Record<string, string> = { manual: "apply on employer site", email: "apply by email", mock: "demo" };
const OUTCOME_LABELS: Record<string, string> = { confirmed: "confirmed received", uncertain: "sent, not yet confirmed", failed: "failed" };
const ATTEMPT_LABELS: Record<string, string> = {
  started: "in progress",
  succeeded: "sent",
  uncertain: "sent, not confirmed",
  unknown: "result unknown",
  failed_retryable: "failed, can retry",
  failed_permanent: "couldn't apply automatically",
  failed: "failed",
};
const SOURCE_LABELS: Record<string, string> = { profile: "from your profile", resume: "from your resume", user: "your answer", none: "" };

function ApplicationCard({ app, open, onToggle }: { app: Application; open: boolean; onToggle: () => void }) {
  const cardRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (open) cardRef.current?.scrollIntoView({ block: "nearest" });
  }, [open]);
  const post = (path: string, body?: unknown) => api<unknown>(`/applications/${app.id}${path}`, { method: "POST", body: body ?? {} });
  const approve = useAction(() => post("/approve", { submit_now: true }));
  const reject = useAction(() => post("/reject", { note: "declined in queue" }));
  const submit = useAction(() => post("/submit"));
  const retry = useAction(() => post("/retry"));
  const hold = useAction(() => post("/hold", { note: "held from the queue" }));
  const verify = useAction(() => api<{ result: string }>(`/applications/${app.id}/verify`, { method: "POST" }));
  const [confirming, setConfirming] = useState(false);
  const [ref, setRef] = useState("");
  const [note, setNote] = useState("");
  const confirm = useAction(() => post("/confirm-manual", { reference: ref || null, note: note || null }), () => setConfirming(false));

  const status = app.job_status;
  const blockers = app.approval_blockers ?? [];
  const lastAttempt = app.attempts[app.attempts.length - 1];
  const unknown = app.attempts.some((t) => t.status === "unknown" || t.status === "started");
  const error = approve.error || reject.error || submit.error || hold.error || retry.error || verify.error || confirm.error;
  const applyLink = app.apply_url || app.job_url;
  const scheduled = status === "ready_to_apply" && app.mode === "automatic" && !app.approved_at && app.scheduled_for;
  // The reason is often repeated as a warning; show it once, as a sentence.
  const reason = app.status_reason ? app.status_reason.charAt(0).toUpperCase() + app.status_reason.slice(1) : null;
  const warnings = (app.warnings ?? []).filter((w) => w.trim().toLowerCase() !== app.status_reason?.trim().toLowerCase());
  const attention = needsYou(app);

  return (
    <div ref={cardRef} className="min-w-0 scroll-mt-20 rounded-2xl border border-slate-200/80 bg-white shadow-soft">
      <button type="button" aria-expanded={open} onClick={onToggle} className="flex w-full items-center gap-3 rounded-2xl px-4 py-3.5 text-left transition hover:bg-slate-50/80 sm:px-5">
        <span className="min-w-0 flex-1">
          <span className="block truncate font-medium text-slate-900">{app.job_title}</span>
          <span className="mt-1 flex flex-wrap items-center gap-1.5 text-sm text-slate-500">
            <span className="mr-1">{app.company}</span>
            <StatusBadge status={status} />
            {attention && <Badge tone="red">needs you</Badge>}
            {app.outcome !== "pending" && <Badge tone={outcomeTone(app.outcome)}>{OUTCOME_LABELS[app.outcome] ?? app.outcome}</Badge>}
            {status !== "needs_manual" && <Badge>{ROUTE_LABELS[app.route] ?? app.route}</Badge>}
            {app.mode === "automatic" && <Badge tone="amber">applies automatically</Badge>}
          </span>
        </span>
        <ChevronDown className={cx("size-5 shrink-0 text-slate-400 transition", open && "rotate-180")} aria-hidden />
      </button>
      {open && (
      <div className="border-t border-slate-100 p-4 sm:p-5">
      <Link className="mb-3 inline-block text-sm text-indigo-700 hover:underline" to={`/jobs/${app.job_id}`}>
        View the job →
      </Link>
      <div className="grid gap-4 md:grid-cols-2">
        <div className="space-y-3">
          {reason && <p className="text-sm text-slate-600">{reason}</p>}
          {scheduled && (
            <Alert tone="info">
              Applies automatically on <strong>{formatDate(app.scheduled_for, true)}</strong>, in a recruiter-friendly send window. Choose <b>Hold</b> to review it first.
            </Alert>
          )}
          {blockers.length > 0 && (
            <Alert tone="error">
              <strong>Fix before approving:</strong>
              <List items={blockers} />
            </Alert>
          )}
          {warnings.length > 0 && (
            <Alert tone="warning">
              <strong>Review:</strong>
              <List items={warnings} />
            </Alert>
          )}
          {(app.auto_blockers ?? []).length > 0 && (
            <details className="text-sm text-slate-600">
              <summary className="cursor-pointer">Why this is not automatic ({app.auto_blockers!.length})</summary>
              <List items={app.auto_blockers} />
            </details>
          )}
          <div className="text-sm">
            Resume:{" "}
            {app.resume_version_id ? (
              <Link className="text-indigo-700 hover:underline" to={`/resumes/${app.resume_version_id}`}>
                tailored for this job
              </Link>
            ) : (
              "not generated yet"
            )}{" "}
            {app.resume_valid !== undefined && <Badge tone={app.resume_valid ? "green" : "red"}>{app.resume_valid ? "ready to send" : "needs fixing"}</Badge>}
            {app.route === "email" && app.apply_email && <span className="ml-2 text-slate-600">sends to {app.apply_email}</span>}
          </div>
          {lastAttempt && !(app.route === "manual" && lastAttempt.status === "failed_permanent") && (
            <div className="text-sm text-slate-600">
              Last try: <Badge>{ATTEMPT_LABELS[lastAttempt.status] ?? lastAttempt.status}</Badge> {lastAttempt.error && <span>— {lastAttempt.error}</span>}
            </div>
          )}
        </div>
        <div>
          <h3 className="mb-2 text-sm font-semibold">Application answers</h3>
          {app.answers.length === 0 ? <Empty>This application has no form questions.</Empty> : <Answers app={app} />}
        </div>
      </div>

      {app.route === "manual" && ["awaiting_approval", "ready_to_apply", "needs_manual"].includes(status) && <ApplyKit app={app} applyLink={applyLink} />}

      <div className="mt-4 flex flex-wrap gap-2 border-t border-slate-100 pt-3">
        {status === "awaiting_approval" && (
          <>
            {app.route !== "manual" && (
              <Button variant="primary" busy={approve.isPending} disabled={blockers.length > 0} onClick={() => approve.mutate()}>
                Approve and submit
              </Button>
            )}
          </>
        )}
        {status === "ready_to_apply" && app.route !== "manual" && (
          <Button variant="primary" busy={submit.isPending} onClick={() => submit.mutate()}>
            Submit now
          </Button>
        )}
        {scheduled && (
          <Button busy={hold.isPending} onClick={() => hold.mutate()}>
            Hold for review
          </Button>
        )}
        {status === "application_failed" && lastAttempt?.status === "failed_retryable" && (
          <Button busy={retry.isPending} onClick={() => retry.mutate()}>
            Retry
          </Button>
        )}
        {unknown && (
          <Button busy={verify.isPending} onClick={() => verify.mutate()}>
            Verify whether it arrived
          </Button>
        )}
        {(app.route === "manual" || ["needs_manual", "application_failed"].includes(status)) && (
          <a href={applyLink} target="_blank" rel="noopener noreferrer nofollow" className="inline-flex items-center gap-1.5 rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm hover:bg-slate-50">
            Open job page <ExternalLink className="size-3.5" aria-hidden />
          </a>
        )}
        {["awaiting_approval", "ready_to_apply", "needs_manual", "application_failed"].includes(status) && (
          <Button variant={app.route === "manual" ? "primary" : "secondary"} onClick={() => setConfirming(!confirming)}>
            I applied
          </Button>
        )}
        {status === "awaiting_approval" && (
          <Button
            variant="ghost"
            className="ml-auto text-red-600"
            busy={reject.isPending}
            onClick={() => window.confirm(`Decline the application for ${app.job_title} at ${app.company}?`) && reject.mutate()}
          >
            Decline
          </Button>
        )}
      </div>
      {verify.data && (
        <div className="mt-2">
          <Alert tone="info">
            Verification result: {verify.data.result === "received" ? "the employer received it" : verify.data.result === "not_received" ? "it did not arrive; it is safe to retry" : "this route cannot verify; check with the employer"}.
          </Alert>
        </div>
      )}
      {confirming && (
        <form
          className="mt-3 grid gap-3 rounded border border-slate-200 p-3 md:grid-cols-3"
          onSubmit={(e) => {
            e.preventDefault();
            confirm.mutate();
          }}
        >
          <Field label="Confirmation or reference number" hint="Without one, the application is recorded as uncertain.">
            <TextInput value={ref} onChange={(e) => setRef(e.target.value)} />
          </Field>
          <Field label="Note" className="md:col-span-2">
            <TextInput value={note} onChange={(e) => setNote(e.target.value)} />
          </Field>
          <div className="md:col-span-3">
            <Button type="submit" variant="primary" busy={confirm.isPending}>
              Record application
            </Button>
          </div>
        </form>
      )}
      <div className="mt-2">
        <ErrorText error={error} />
      </div>
      </div>
      )}
    </div>
  );
}

function Answers({ app }: { app: Application }) {
  return (
    <ul className="space-y-2">
      {app.answers.map((a) => (
        <AnswerRow key={a.id} appId={app.id} answer={a} editable={app.outcome === "pending"} />
      ))}
    </ul>
  );
}

function AnswerRow({ appId, answer, editable }: { appId: number; answer: Answer; editable: boolean }) {
  // A hidden (sensitive) answer is never pre-filled: saving "••••" would send that to the employer.
  const masked = answer.answer === "••••";
  const [value, setValue] = useState(answer.needs_user || masked ? "" : (answer.answer ?? ""));
  const save = useAction(() => api(`/applications/${appId}/answers`, { method: "PUT", body: { answer_id: answer.id, answer: value } }));
  return (
    <li className="rounded border border-slate-100 p-2 text-sm">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="font-medium text-slate-800">{answer.question}</span>
        {answer.sensitive && <Badge tone="amber">private</Badge>}
        {answer.needs_user ? <Badge tone="red">needs your answer</Badge> : SOURCE_LABELS[answer.source] ? <Badge tone="green">{SOURCE_LABELS[answer.source]}</Badge> : null}
      </div>
      {editable ? (
        <div className="mt-1 flex gap-2">
          <TextArea rows={answer.category === "free_text" ? 3 : 1} value={value} placeholder={masked ? "Saved and hidden — type to change it" : undefined} onChange={(e) => setValue(e.target.value)} aria-label={`Answer: ${answer.question}`} />
          <Button busy={save.isPending} disabled={!value.trim()} onClick={() => save.mutate()}>
            Save
          </Button>
        </div>
      ) : (
        <p className="mt-1 text-slate-600">{answer.answer ?? "—"}</p>
      )}
      <ErrorText error={save.error} />
    </li>
  );
}

export function AttemptTable({ app }: { app: Application }) {
  return (
    <table className="w-full text-left text-xs">
      <thead className="text-slate-500">
        <tr>
          <th className="py-1">#</th>
          <th>Status</th>
          <th>Trigger</th>
          <th>Started</th>
          <th>Finished</th>
          <th>Error</th>
        </tr>
      </thead>
      <tbody>
        {app.attempts.map((t) => (
          <tr key={t.attempt_no} className="border-t border-slate-100">
            <td className="py-1">{t.attempt_no}</td>
            <td>{t.status}</td>
            <td>{t.trigger}</td>
            <td>{formatDate(t.started_at, true)}</td>
            <td>{formatDate(t.finished_at, true)}</td>
            <td>{t.error ?? ""}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

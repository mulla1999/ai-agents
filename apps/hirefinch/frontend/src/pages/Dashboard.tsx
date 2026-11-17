import { useQuery } from "@tanstack/react-query";
import { AlertCircle, ArrowRight, Briefcase, CalendarCheck, ClipboardCheck, FileText, Mail, RefreshCw, Send, Sparkles, Star, type LucideIcon } from "lucide-react";
import { Link, useNavigate } from "react-router";
import { useMe } from "../auth";
import { api } from "../api/client";
import { TopSkillGaps } from "../components/SkillGaps";
import type { Dashboard, RunReport } from "../api/types";
import { Alert, Badge, Button, Card, ErrorText, Loading, PageHeader, cx, formatDate, useAction } from "../components/ui";
import { describeEvent, isHousekeeping } from "./Audit";

const METRICS: { key: keyof Dashboard["metrics"]; label: string; to: string; icon: LucideIcon; tone: string }[] = [
  { key: "discovered_today", label: "Discovered today", to: "/jobs?sort=recent", icon: Briefcase, tone: "bg-sky-50 text-sky-600" },
  { key: "high_match", label: "High-match jobs", to: "/jobs?min_score=85", icon: Star, tone: "bg-emerald-50 text-emerald-600" },
  { key: "awaiting_resume_review", label: "Resumes to review", to: "/jobs?status=resume_ready", icon: FileText, tone: "bg-violet-50 text-violet-600" },
  { key: "pending_approvals", label: "Pending approvals", to: "/queue", icon: ClipboardCheck, tone: "bg-amber-50 text-amber-600" },
  { key: "applications_submitted", label: "Applications submitted", to: "/tracker", icon: Send, tone: "bg-indigo-50 text-indigo-600" },
  { key: "recruiters_contacted", label: "Recruiters contacted", to: "/outreach", icon: Mail, tone: "bg-cyan-50 text-cyan-600" },
  { key: "interviews", label: "Interviews", to: "/jobs?status=interview_scheduled", icon: CalendarCheck, tone: "bg-teal-50 text-teal-600" },
  { key: "needs_attention", label: "Needs attention", to: "/queue", icon: AlertCircle, tone: "bg-rose-50 text-rose-600" },
];

const STAGE_LABELS: Record<string, string> = {
  evaluated: "scored",
  shortlisted: "shortlisted",
  resume: "resumes tailored",
  prepared: "applications prepared",
  submitted: "applications sent",
  outreach_scheduled: "recruiter emails scheduled",
  outreach_sent: "recruiter emails sent",
  base_resume_email: "emails drafted",
};

const PROMPTS = ["Show my best matches posted this week", "What's my application status?", "What's missing in my profile?"];

const SUMMARY_LABELS: Record<string, string> = {
  discovered: "Jobs discovered",
  qualified: "Qualified matches",
  applications: "Applications",
  outreach_sent: "Recruiter emails",
  pending_approvals: "Pending approvals",
  interviews: "Interviews",
  errors: "Errors",
  dead_notifications: "Notification emails that failed",
};

const MODE_TEXT: Record<Dashboard["mode"], string> = {
  supervised: "You approve every application",
  automatic: "Applies automatically when it's sure",
};

// "2026-11-01" → "1 Nov", read as a calendar date (no time-zone shift).
const shortDay = (iso: string) => {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString(undefined, { day: "numeric", month: "short" });
};

export function DashboardPage() {
  const query = useQuery({ queryKey: ["dashboard"], queryFn: () => api<Dashboard>("/dashboard"), refetchInterval: 30_000 });
  const run = useAction(() => api<RunReport>("/automation/run", { method: "POST" }));
  const me = useMe();
  const navigate = useNavigate();

  if (query.isLoading) return <Loading />;
  if (query.error) return <ErrorText error={query.error} />;
  const d = query.data!;
  const funnelMax = Math.max(1, ...Object.values(d.funnel));
  const trendMax = Math.max(1, ...d.trend.map((t) => Math.max(t.discovered, t.applied)));
  const activity = d.recent_activity.filter((e) => !isHousekeeping(e)); // sign-ins and admin changes live in the Activity Log

  return (
    <>
      <PageHeader
        title={`Welcome back${me.full_name ? `, ${me.full_name.split(" ")[0]}` : ""}`}
        subtitle={
          <span className="inline-flex flex-wrap items-center gap-2">
            Mode:
            <Link to="/automation" className="hover:opacity-80" title="Change in Automation">
              <Badge tone={d.mode === "automatic" ? "amber" : "indigo"}>{MODE_TEXT[d.mode] ?? d.mode}</Badge>
            </Link>
            {d.paused && <Badge tone="amber">paused</Badge>}
            {d.emergency_stop && <Badge tone="red">emergency stop</Badge>}
          </span>
        }
        actions={
          <Button variant="primary" busy={run.isPending} onClick={() => run.mutate()}>
            <RefreshCw className="size-4" aria-hidden /> Run discovery now
          </Button>
        }
      />
      <div className="space-y-4">
        {run.data && (
          <Alert tone={run.data.errors.length ? "warning" : "success"}>
            Search finished: {run.data.new_jobs ?? 0} new job{run.data.new_jobs === 1 ? "" : "s"} found
            {Object.entries(run.data.advanced).length > 0 &&
              `; ${Object.entries(run.data.advanced).map(([k, v]) => `${v} ${STAGE_LABELS[k] ?? k.replaceAll("_", " ")}`).join(", ")}`}
            .
            {run.data.errors.length > 0 && <> Errors: {run.data.errors.join("; ")}</>}
          </Alert>
        )}
        <ErrorText error={run.error} />
        {d.warnings.map((w, i) => (
          <Alert key={i} tone={w.level}>
            {w.message}
          </Alert>
        ))}

        <section className="relative overflow-hidden rounded-2xl bg-gradient-to-br from-indigo-600 via-indigo-600 to-violet-700 p-6 text-white shadow-lift">
          <div className="absolute -right-16 -top-16 size-64 rounded-full bg-white/10 blur-2xl" aria-hidden />
          <div className="relative flex flex-wrap items-center justify-between gap-4">
            <div className="max-w-xl">
              <p className="inline-flex items-center gap-1.5 rounded-full bg-white/15 px-2.5 py-0.5 text-xs font-medium">
                <Sparkles className="size-3.5" aria-hidden /> Job assistant
              </p>
              <h2 className="mt-2 text-xl font-semibold tracking-tight">Tell me what you're looking for, and I'll do the legwork.</h2>
              <p className="mt-1 text-sm text-indigo-100">Find matching jobs, see why they fit, apply after you confirm and write to recruiters, all from one chat.</p>
            </div>
            <Link to="/assistant" className="inline-flex items-center gap-2 rounded-xl bg-white px-4 py-2.5 text-sm font-semibold text-indigo-700 shadow-sm transition hover:bg-indigo-50">
              Open assistant <ArrowRight className="size-4" aria-hidden />
            </Link>
          </div>
          <div className="relative mt-4 flex flex-wrap gap-2">
            {PROMPTS.map((p) => (
              <button key={p} type="button" onClick={() => navigate(`/assistant?c=new&q=${encodeURIComponent(p)}`)} className="rounded-full bg-white/10 px-3 py-1 text-xs text-white ring-1 ring-inset ring-white/20 transition hover:bg-white/20">
                {p}
              </button>
            ))}
          </div>
        </section>

        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          {METRICS.map((m) => {
            const Icon = m.icon;
            return (
              <Link key={m.key} to={m.to} className="group rounded-2xl border border-slate-200/80 bg-white p-4 shadow-soft transition hover:-translate-y-0.5 hover:border-indigo-200 hover:shadow-lift">
                <span className={`grid size-9 place-items-center rounded-xl ${m.tone}`}>
                  <Icon className="size-4.5" aria-hidden />
                </span>
                <div className="mt-3 text-2xl font-semibold tabular-nums tracking-tight text-slate-900">{d.metrics[m.key]}</div>
                <div className="text-xs text-slate-500 group-hover:text-slate-700">{m.label}</div>
              </Link>
            );
          })}
        </div>

        <TopSkillGaps />

        <div className="grid gap-4 lg:grid-cols-2">
          <Card title="Application funnel">
            <div className="space-y-2">
              {Object.entries(d.funnel).map(([stage, value]) => (
                <div key={stage} className="flex items-center gap-3 text-sm">
                  <span className="w-24 shrink-0 capitalize text-slate-600">{stage}</span>
                  <div className="h-2.5 flex-1 overflow-hidden rounded-full bg-slate-100">
                    <div className="h-2.5 rounded-full bg-gradient-to-r from-indigo-500 to-violet-500" style={{ width: `${(value / funnelMax) * 100}%` }} />
                  </div>
                  <span className="w-10 text-right font-medium tabular-nums">{value}</span>
                </div>
              ))}
            </div>
          </Card>
          <Card title="Last 14 days">
            <div className="flex h-40 items-end gap-1" role="img" aria-label="Jobs discovered and applications submitted per day">
              {d.trend.map((t) => (
                <div key={t.date} className="flex h-full flex-1 flex-col justify-end gap-0.5" title={`${t.date}: ${t.discovered} discovered, ${t.applied} applied`}>
                  <div className="rounded-t bg-indigo-300" style={{ height: `${(t.discovered / trendMax) * 100}%` }} />
                  <div className="rounded-t bg-emerald-500" style={{ height: `${(t.applied / trendMax) * 100}%` }} />
                </div>
              ))}
            </div>
            {/* A date under every other bar; the newest day is always labelled. */}
            <div className="mt-1 flex gap-1 text-[0.625rem] text-slate-500" aria-hidden>
              {d.trend.map((t, i) => (
                <span key={t.date} className="flex-1 whitespace-nowrap text-center">
                  {(d.trend.length - 1 - i) % 2 === 0 ? shortDay(t.date) : ""}
                </span>
              ))}
            </div>
            <div className="mt-2 flex justify-center text-xs text-slate-500">
              <span className="flex gap-3">
                <span className="inline-flex items-center gap-1">
                  <span className="size-2 rounded-sm bg-indigo-300" /> discovered
                </span>
                <span className="inline-flex items-center gap-1">
                  <span className="size-2 rounded-sm bg-emerald-500" /> applied
                </span>
              </span>
            </div>
          </Card>
        </div>

        <div className="grid gap-4 lg:grid-cols-3">
          <Card title="Last 24 hours">
            <dl className="space-y-1.5 text-sm">
              {Object.entries(d.summary).map(([key, value]) => (
                <div key={key} className="flex justify-between gap-3">
                  <dt className="text-slate-600">{SUMMARY_LABELS[key] ?? key.replaceAll("_", " ")}</dt>
                  <dd className="font-medium tabular-nums">{value}</dd>
                </div>
              ))}
            </dl>
            {Number(d.summary.dead_notifications) > 0 && (
              <p className="mt-3 text-xs text-slate-500">
                Some notification emails couldn't be delivered. Check{" "}
                <Link to="/integrations" className="text-indigo-700 hover:underline">
                  your email connection
                </Link>{" "}
                and your notification address in Profile.
              </p>
            )}
          </Card>
          <Card title="Recent activity" className="lg:col-span-2" actions={<Link className="text-sm text-indigo-600 hover:underline" to="/audit">All activity</Link>}>
            <ul className="divide-y divide-slate-100 text-sm">
              {activity.map((e) => {
                const { text, to } = describeEvent(e);
                return (
                  <li key={e.id} className="flex flex-col gap-0.5 py-2 sm:flex-row sm:items-center sm:gap-3">
                    <span className="shrink-0 text-xs text-slate-500 sm:w-36">{formatDate(e.at, true)}</span>
                    <span className={cx("min-w-0 flex-1 text-slate-700 sm:truncate", e.level === "error" && "text-red-700", e.level === "warning" && "text-amber-800")} title={text}>
                      {to ? (
                        <Link to={to} className="hover:text-indigo-700 hover:underline">
                          {text}
                        </Link>
                      ) : (
                        text
                      )}
                    </span>
                  </li>
                );
              })}
              {activity.length === 0 && <li className="py-2 text-slate-500">Nothing yet. Run a search to get started.</li>}
            </ul>
          </Card>
        </div>
      </div>
    </>
  );
}

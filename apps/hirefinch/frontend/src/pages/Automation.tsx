import { useQuery } from "@tanstack/react-query";
import { OctagonX, Pause, Play } from "lucide-react";
import { useState, type ReactNode } from "react";
import { api } from "../api/client";
import type { Automation, AutomationPolicy, OutboxItem } from "../api/types";
import { Alert, Badge, Button, Card, Collapsible, ErrorText, Field, ListInput, Loading, NumberInput, PageHeader, Select, TextInput, cx, formatDate, useAction } from "../components/ui";

const NOTIFY = [
  "application_submitted",
  "application_uncertain",
  "application_failed",
  "outreach_sent",
  "approval_required",
  "resume_ready",
  "high_priority_job",
  "daily_summary",
  "connector_auth_expired",
  "automation_stopped",
];

// A checkbox row big enough to tap on a phone: the whole row toggles it.
function Tick({ label, checked, onChange, disabled = false }: { label: ReactNode; checked: boolean; onChange: (v: boolean) => void; disabled?: boolean }) {
  return (
    <label className={cx("flex min-h-11 items-center gap-3 rounded-lg px-1 text-sm text-slate-700", disabled ? "cursor-not-allowed opacity-50" : "cursor-pointer hover:bg-slate-50")}>
      <input type="checkbox" disabled={disabled} className="size-5 shrink-0 rounded border-slate-300 accent-indigo-600" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      <span>{label}</span>
    </label>
  );
}

export function AutomationPage() {
  const query = useQuery({ queryKey: ["automation"], queryFn: () => api<Automation>("/automation") });
  if (query.isLoading) return <Loading />;
  if (query.error) return <ErrorText error={query.error} />;
  return (
    <>
      <PageHeader title="Automation Settings" subtitle="How much HireFinch does on its own. By default it asks you before every application and recruiter email." />
      <div className="space-y-4">
        <Controls a={query.data!} />
        <PolicyForm key={JSON.stringify(query.data!.policy)} a={query.data!} />
        <Outbox />
      </div>
    </>
  );
}

function Controls({ a }: { a: Automation }) {
  const [reason, setReason] = useState("");
  const control = useAction((body: { action: string; reason?: string }) => api("/automation/control", { method: "POST", body }));
  return (
    <Card title="Pause or stop">
      {a.emergency_stop && <Alert tone="error">Emergency stop is on{a.stop_reason ? `: ${a.stop_reason}` : ""}. Nothing is submitted or sent, including things you approved.</Alert>}
      {a.paused && !a.emergency_stop && <Alert tone="warning">Paused: HireFinch isn't searching or preparing anything on its own. You can still do things yourself.</Alert>}
      {!a.paused && !a.emergency_stop && (
        <p className="text-sm text-slate-600">
          <b>Pause</b> stops the scheduled job search and preparation; you can still act yourself. <b>Emergency stop</b> blocks every send, even ones you approved.
        </p>
      )}
      <div className="mt-3 flex flex-wrap items-end gap-2">
        {a.paused ? (
          <Button busy={control.isPending} onClick={() => control.mutate({ action: "resume" })}>
            <Play className="size-4" aria-hidden /> Resume
          </Button>
        ) : (
          <Button busy={control.isPending} onClick={() => control.mutate({ action: "pause" })}>
            <Pause className="size-4" aria-hidden /> Pause
          </Button>
        )}
        {a.emergency_stop ? (
          <Button busy={control.isPending} onClick={() => control.mutate({ action: "clear_stop" })}>
            Clear emergency stop
          </Button>
        ) : (
          <>
            <Field label="Reason (optional)" className="w-full sm:w-64">
              <TextInput value={reason} placeholder="e.g. on holiday" onChange={(e) => setReason(e.target.value)} />
            </Field>
            <Button variant="danger" busy={control.isPending} onClick={() => control.mutate({ action: "stop", reason: reason || undefined })}>
              <OctagonX className="size-4" aria-hidden /> Emergency stop
            </Button>
          </>
        )}
      </div>
      <ErrorText error={control.error} />
    </Card>
  );
}

const NOTIFY_LABELS: Record<string, string> = {
  application_submitted: "An application was sent",
  application_uncertain: "An application may not have arrived",
  application_failed: "An application failed",
  outreach_sent: "A recruiter email was sent",
  approval_required: "Something needs your approval",
  resume_ready: "A tailored resume is ready",
  high_priority_job: "A strong new match was found",
  daily_summary: "Daily summary",
  connector_auth_expired: "A job source needs you to sign in again",
  automation_stopped: "Automation was stopped",
};

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function PolicyForm({ a }: { a: Automation }) {
  const [p, setP] = useState<AutomationPolicy>(a.policy);
  const [confirmation, setConfirmation] = useState("");
  const save = useAction(() => api("/automation", { method: "PUT", body: { policy: p, confirmation: confirmation || null } }));
  const escalating = (p.mode === "automatic" && a.policy.mode !== "automatic") || (p.auto_send_outreach && !a.policy.auto_send_outreach);
  const needsPhrase = escalating && confirmation !== a.confirmation_phrase;
  const supervised = p.mode === "supervised";
  const num = (key: keyof AutomationPolicy, label: string, hint?: string, extra: Record<string, number> = {}, disabled = false) => (
    <Field label={label} hint={hint}>
      <NumberInput value={p[key] as number} disabled={disabled} {...extra} onChange={(v) => setP({ ...p, [key]: v ?? 0 })} />
    </Field>
  );
  return (
    <Card title="How HireFinch works for you">
      <div className="grid gap-3 md:grid-cols-3">
        <Field label="Applications" className="md:col-span-3">
          <Select value={p.mode} onChange={(e) => setP({ ...p, mode: e.target.value as AutomationPolicy["mode"] })}>
            <option value="supervised">Ask me before every application (recommended)</option>
            <option value="automatic">Apply on my behalf when every condition holds</option>
          </Select>
        </Field>
      </div>
      <div className={cx("mt-3 rounded-xl border p-3", supervised ? "border-slate-200 bg-slate-50" : "border-amber-200 bg-amber-50/40")}>
        <p className="text-sm font-medium text-slate-800">Automatic applications</p>
        {supervised && <p className="text-xs text-slate-500">Off while HireFinch asks you first. Choose “Apply on my behalf” above to use these.</p>}
        <div className="mt-1 grid gap-3 md:grid-cols-3">
          {num("auto_apply_min_score", "Only for match score ≥", "Minimum 70", { min: 70, max: 100 }, supervised)}
          <div className="flex items-end md:col-span-2">
            <Tick
              disabled={supervised}
              label="Apply automatically by email (when the job gives an application address)"
              checked={p.auto_apply_routes.includes("email")}
              onChange={(v) => setP({ ...p, auto_apply_routes: v ? [...new Set([...p.auto_apply_routes, "email"])] : p.auto_apply_routes.filter((r) => r !== "email") })}
            />
          </div>
        </div>
      </div>
      <div className="mt-3 grid gap-x-3 md:grid-cols-2">
        <Tick label="Send recruiter emails automatically" checked={p.auto_send_outreach} onChange={(v) => setP({ ...p, auto_send_outreach: v })} />
        <Tick label="Use AI to improve resume summaries, bullets and recruiter emails (fact-checked)" checked={p.use_llm_for_tailoring} onChange={(v) => setP({ ...p, use_llm_for_tailoring: v })} />
      </div>

      <h3 className="mb-2 mt-5 text-sm font-semibold">Limits</h3>
      <div className="grid gap-3 md:grid-cols-3">
        {num("daily_application_limit", "Applications per day", undefined, { min: 0 })}
        {num("weekly_application_limit", "Applications per week", undefined, { min: 0 })}
        {num("outreach_daily_limit", "Recruiter emails per day", `Platform cap: ${a.limits.daily_outreach_cap} per day`, { min: 0 })}
      </div>

      <h3 className="mb-1 mt-5 text-sm font-semibold">When automatic actions happen</h3>
      <p className="mb-2 text-sm text-slate-600">
        Automatic applications and recruiter emails wait for the review period, then go out in the next send window, when recruiters are at their desks. Anything you approve yourself is sent at once.
      </p>
      <div className="grid gap-3 md:grid-cols-3">
        <Field label="Send days">
          <div className="flex flex-wrap gap-x-2">
            {DAYS.map((d, i) => (
              <Tick
                key={d}
                label={d}
                checked={p.send_days.includes(i)}
                onChange={(v) => setP({ ...p, send_days: v ? [...p.send_days, i].sort() : p.send_days.filter((x) => x !== i) })}
              />
            ))}
          </div>
        </Field>
        <Field label="Send times (your time)" hint="Start-end, comma-separated, e.g. 09:30-12:30, 14:00-17:00">
          <ListInput value={p.send_windows} rows={2} onChange={(v) => setP({ ...p, send_windows: v })} />
        </Field>
        {num("auto_review_minutes", "Wait before sending (minutes)", "Time to look and choose Hold", { min: 0, max: 1440 })}
      </div>

      <details className="mt-5 rounded-xl border border-slate-200 px-4 py-2 text-sm">
        <summary className="cursor-pointer py-1 font-medium text-slate-700">Notifications: what HireFinch emails you about</summary>
        <div className="mt-1 grid gap-x-3 pb-2 md:grid-cols-2">
          {NOTIFY.map((n) => (
            <Tick key={n} label={NOTIFY_LABELS[n] ?? n.replaceAll("_", " ")} checked={p.notify.includes(n)} onChange={(v) => setP({ ...p, notify: v ? [...p.notify, n] : p.notify.filter((x) => x !== n) })} />
          ))}
        </div>
      </details>

      <details className="mt-3 rounded-xl border border-slate-200 px-4 py-2 text-sm">
        <summary className="cursor-pointer py-1 font-medium text-slate-700">Advanced: scores, search schedule and resume length</summary>
        <div className="mt-2 grid gap-3 pb-2 md:grid-cols-3">
          {num("shortlist_min_score", "Shortlist jobs scoring ≥", undefined, { min: 0, max: 100 })}
          {num("tailor_min_score", "Tailor a resume for jobs scoring ≥", undefined, { min: 0, max: 100 })}
          {num("discovery_interval_minutes", "Search for new jobs every (minutes)", `At least ${a.limits.min_discovery_minutes} minutes`, {
            min: a.limits.min_discovery_minutes,
          })}
          <Field label="Search hours (your time)" hint="Looks for new jobs only in these hours">
            <TextInput value={p.discovery_hours} onChange={(e) => setP({ ...p, discovery_hours: e.target.value })} />
          </Field>
          {num("digest_hour_local", "Daily summary at (hour, 0-23)", undefined, { min: 0, max: 23 })}
          <Field label="Timezone" hint="e.g. Asia/Kolkata">
            <TextInput value={p.timezone} onChange={(e) => setP({ ...p, timezone: e.target.value })} />
          </Field>
          {num("max_bullets_older_roles", "Bullet points per older job on tailored resumes", undefined, { min: 1, max: 12 })}
        </div>
      </details>

      {escalating && (
        <div className="mt-4 space-y-2">
          <Alert tone="warning">
            You are turning on {p.mode === "automatic" && a.policy.mode !== "automatic" ? "automatic applications" : "automatic recruiter emails"}. HireFinch will act without asking, within the limits above. Type{" "}
            <strong>{a.confirmation_phrase}</strong> to confirm.
          </Alert>
          <Field label="Confirmation phrase" className="max-w-sm">
            <TextInput value={confirmation} onChange={(e) => setConfirmation(e.target.value)} />
          </Field>
        </div>
      )}
      <div className="mt-5 border-t border-slate-100 pt-4">
        <Button variant="primary" busy={save.isPending} disabled={needsPhrase} onClick={() => save.mutate()}>
          Save settings
        </Button>
        {needsPhrase && <span className="ml-3 text-xs text-amber-700">Type the confirmation phrase above first.</span>}
        <div className="mt-2">
          <ErrorText error={save.error} />
          {save.isSuccess && <Alert tone="success">Settings saved.</Alert>}
        </div>
      </div>
    </Card>
  );
}

const KIND_LABELS: Record<string, string> = {
  application_submitted: "Application sent",
  application_uncertain: "Application may not have arrived",
  application_failed: "Application failed",
  outreach_sent: "Recruiter email sent",
  approval_required: "Approval needed",
  resume_ready: "Resume ready",
  high_priority_job: "Strong new match",
  daily_summary: "Daily summary",
  connector_auth_expired: "Job source needs sign-in",
  automation_stopped: "Automation stopped",
};
const kindLabel = (k: string) => KIND_LABELS[k] ?? k.replaceAll("_", " ").replace(/^./, (c) => c.toUpperCase());
const STATUS: Record<string, [string, "green" | "red" | "amber" | "slate"]> = {
  sent: ["sent", "green"],
  dead: ["not delivered", "red"],
  failed: ["retrying", "amber"],
  pending: ["waiting", "amber"],
  held: ["waiting", "amber"],
};

function Outbox() {
  const query = useQuery({ queryKey: ["outbox"], queryFn: () => api<OutboxItem[]>("/notifications") });
  const process = useAction(() => api<{ sent: number; failed: number; held: number }>("/notifications/process", { method: "POST" }));
  const digest = useAction(() => api<{ queued: boolean }>("/notifications/digest", { method: "POST" }));
  const latest = [...(query.data ?? [])].sort((x, y) => y.created_at.localeCompare(x.created_at)).slice(0, 10);
  const waiting = (query.data ?? []).filter((n) => n.status !== "sent" && n.status !== "dead").length;
  return (
    <Collapsible summary={`Emails HireFinch sent you${waiting ? ` · ${waiting} waiting to go out` : ""}. Shows the latest 10.`}>
      <Card title="Delivery history">
        {query.isLoading ? (
          <Loading />
        ) : query.error ? (
          <ErrorText error={query.error} />
        ) : latest.length === 0 ? (
          <p className="text-sm text-slate-500">Nothing sent to you yet.</p>
        ) : (
          <ul className="divide-y divide-slate-100 text-sm">
            {latest.map((n) => {
              const [label, tone] = STATUS[n.status] ?? [n.status, "slate"];
              return (
                <li key={n.id} className="py-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge tone={tone}>{label}</Badge>
                    <span className="font-medium text-slate-800">{kindLabel(n.kind)}</span>
                    <span className="text-xs text-slate-500">{formatDate(n.created_at, true)}</span>
                  </div>
                  <p className="mt-0.5 truncate text-slate-600">{n.subject}</p>
                  {n.last_error && n.status !== "sent" && <p className="text-xs text-slate-500">Problem: {n.last_error}</p>}
                </li>
              );
            })}
          </ul>
        )}
        <div className="mt-4 flex flex-wrap gap-2 border-t border-slate-100 pt-3">
          <Button busy={process.isPending} onClick={() => process.mutate()}>
            Send waiting emails now
          </Button>
          <Button busy={digest.isPending} onClick={() => digest.mutate()}>
            Send today's summary
          </Button>
        </div>
        {process.data && (
          <div className="mt-2">
            <Alert tone="info">
              Sent {process.data.sent}, failed {process.data.failed}, still waiting {process.data.held}.
            </Alert>
          </div>
        )}
        {digest.data && (
          <div className="mt-2">
            <Alert tone="info">{digest.data.queued ? "Today's summary is on its way." : "The daily summary is off, or today's was already sent."}</Alert>
          </div>
        )}
        <ErrorText error={process.error || digest.error} />
      </Card>
    </Collapsible>
  );
}

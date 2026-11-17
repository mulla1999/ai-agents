// Small shared UI building blocks. Plain Tailwind, no component library.

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, ChevronDown, Info, Loader2, XCircle } from "lucide-react";
import { createContext, useContext, useId, useState, type ButtonHTMLAttributes, type ReactNode } from "react";
import type { Band, Outcome } from "../api/types";

export function cx(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(" ");
}

type Variant = "primary" | "secondary" | "danger" | "ghost";

export function Button({
  variant = "secondary",
  busy,
  className,
  children,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; busy?: boolean }) {
  const styles: Record<Variant, string> = {
    primary:
      "border-transparent bg-gradient-to-b from-indigo-500 to-indigo-600 text-white shadow-[0_1px_2px_rgb(79_70_229/0.3),inset_0_1px_0_rgb(255_255_255/0.15)] hover:from-indigo-500 hover:to-indigo-700",
    secondary: "border-slate-200 bg-white text-slate-700 shadow-xs hover:border-slate-300 hover:bg-slate-50",
    danger: "border-transparent bg-red-600 text-white shadow-xs hover:bg-red-700",
    ghost: "border-transparent bg-transparent text-slate-600 hover:bg-slate-100 hover:text-slate-900",
  };
  return (
    <button
      type="button"
      {...rest}
      disabled={rest.disabled || busy}
      className={cx(
        "inline-flex items-center justify-center gap-1.5 rounded-lg border px-3.5 py-2 text-sm font-medium transition-all active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-50 disabled:active:scale-100",
        "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-500",
        styles[variant],
        className,
      )}
    >
      {busy && <Loader2 className="size-4 animate-spin" aria-hidden />}
      {children}
    </button>
  );
}

// Wrapping a Card in <Collapsible> makes its header a toggle; the closed card shows only the title and
// a one-line summary. The body stays mounted while closed, so half-filled forms keep their values.
const CollapseContext = createContext<{ open: boolean; toggle: () => void; summary?: ReactNode } | null>(null);

export function Collapsible({ defaultOpen = false, summary, children }: { defaultOpen?: boolean; summary?: ReactNode; children: ReactNode }) {
  const [open, setOpen] = useState(defaultOpen);
  return <CollapseContext.Provider value={{ open, toggle: () => setOpen((o) => !o), summary }}>{children}</CollapseContext.Provider>;
}

export function Card({ title, actions, children, className }: { title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string }) {
  const collapse = useContext(CollapseContext);
  const bodyId = useId();
  if (collapse && title) {
    return (
      <section className={cx("min-w-0 rounded-2xl border border-slate-200/80 bg-white shadow-soft", className)}>
        <h2>
        <button
          type="button"
          onClick={collapse.toggle}
          aria-expanded={collapse.open}
          aria-controls={bodyId}
          className={cx("flex w-full items-center gap-3 rounded-2xl px-5 py-4 text-left transition hover:bg-slate-50/80", collapse.open && "rounded-b-none border-b border-slate-100")}
        >
          <span className="min-w-0 flex-1">
            <span className="block text-[0.9375rem] font-semibold tracking-tight text-slate-900">{title}</span>
            {collapse.summary && <span className="mt-0.5 block text-sm text-slate-500">{collapse.summary}</span>}
          </span>
          <ChevronDown className={cx("size-5 shrink-0 text-slate-400 transition", collapse.open && "rotate-180")} aria-hidden />
        </button>
        </h2>
        <div id={bodyId} hidden={!collapse.open} className="p-5">
          <CollapseContext.Provider value={null}>{children}</CollapseContext.Provider>
        </div>
      </section>
    );
  }
  return (
    <section className={cx("min-w-0 rounded-2xl border border-slate-200/80 bg-white shadow-soft", className)}>
      {(title || actions) && (
        <header className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 px-5 py-3.5">
          {title && <h2 className="text-[0.9375rem] font-semibold tracking-tight text-slate-900">{title}</h2>}
          {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
        </header>
      )}
      <div className="p-5">{children}</div>
    </section>
  );
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
      <div className="max-w-3xl">
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900">{title}</h1>
        {subtitle && <p className="mt-1.5 text-sm leading-relaxed text-slate-500">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  );
}

const TONES = {
  slate: "bg-slate-100 text-slate-700 ring-slate-200",
  indigo: "bg-indigo-50 text-indigo-700 ring-indigo-200",
  green: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  amber: "bg-amber-50 text-amber-800 ring-amber-200",
  red: "bg-red-50 text-red-700 ring-red-200",
  blue: "bg-sky-50 text-sky-700 ring-sky-200",
} as const;
export type Tone = keyof typeof TONES;

export function Badge({ tone = "slate", children, title }: { tone?: Tone; children: ReactNode; title?: string }) {
  return (
    <span title={title} className={cx("inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset whitespace-nowrap", TONES[tone])}>
      {children}
    </span>
  );
}

export function bandTone(band: Band | null | undefined): Tone {
  return band === "high" ? "green" : band === "good" ? "indigo" : band === "review" ? "amber" : band === "disqualified" ? "red" : "slate";
}

// Bands are the agent's recommendation, which also weighs confidence: a 100 based on a short posting is
// "check details", not a grade below a 73 "good".
export const BAND_LABELS: Record<string, string> = { high: "strong fit", good: "good fit", review: "check details", low: "weak fit", disqualified: "not a fit" };
const BAND_HINTS: Record<string, string> = {
  high: "Strong match: worth applying",
  good: "Good match",
  review: "Promising, but the posting is short or unclear: read it before applying",
  low: "Weak match",
  disqualified: "Something in the posting rules this out",
};

export function ScoreBadge({ score, band }: { score: number | null; band: Band | null }) {
  if (score === null) return <Badge>not scored</Badge>;
  return (
    <Badge tone={bandTone(band)} title={band ? BAND_HINTS[band] : undefined}>
      {Math.round(score)} · {band ? (BAND_LABELS[band] ?? band) : ""}
    </Badge>
  );
}

// Where a job or contact came from, in words people know.
const SOURCE_NAMES: Record<string, string> = {
  greenhouse: "Greenhouse",
  lever: "Lever",
  ashby: "Ashby",
  smartrecruiters: "SmartRecruiters",
  career_page: "Company careers page",
  adzuna: "Adzuna",
  jooble: "Jooble",
  themuse: "The Muse",
  job_alerts: "Job alert email",
  manual: "Added by you",
  import: "Imported by you",
  assistant: "Found by the assistant",
  websearch: "Web search",
  job_description: "From the job posting",
  user: "Added by you",
};
const VIA_NAMES: Record<string, string> = { linkedin: "LinkedIn", naukri: "Naukri", indeed: "Indeed", hirist: "Hirist", glassdoor: "Glassdoor" };

export function sourceLabel(source: string | null | undefined, via?: string | null): string {
  if (!source) return "—";
  if (source === "job_alerts" && via) return `${VIA_NAMES[via] ?? via} alert`;
  const name = SOURCE_NAMES[source] ?? source.replaceAll("_", " ").replace(/^./, (c) => c.toUpperCase());
  return via ? `${name} · ${VIA_NAMES[via] ?? via}` : name;
}

export function outcomeTone(outcome: Outcome): Tone {
  return outcome === "confirmed" ? "green" : outcome === "uncertain" ? "amber" : outcome === "failed" ? "red" : "slate";
}

export function statusTone(status: string): Tone {
  if (["applied", "recruiter_contacted", "interview_scheduled"].includes(status)) return "green";
  if (["application_failed", "needs_manual", "rejected"].includes(status)) return "red";
  if (["awaiting_approval", "resume_ready", "ready_to_apply"].includes(status)) return "amber";
  if (["shortlisted", "resume_pending", "application_in_progress"].includes(status)) return "indigo";
  return "slate";
}

/** What each job status means to a job seeker (the API uses internal names). */
export const STATUS_LABELS: Record<string, string> = {
  discovered: "Not scored yet",
  match_evaluated: "New",
  shortlisted: "Shortlisted",
  resume_pending: "Preparing resume",
  resume_ready: "Resume ready",
  awaiting_approval: "Ready for you",
  ready_to_apply: "Ready to apply",
  application_in_progress: "Applying…",
  applied: "Applied",
  recruiter_contacted: "Recruiter contacted",
  interview_scheduled: "Interview",
  rejected: "Rejected",
  withdrawn: "Dismissed",
  expired: "Expired",
  application_failed: "Application failed",
  needs_manual: "Apply on employer site",
};

export const statusLabel = (status: string) => STATUS_LABELS[status] ?? status.replaceAll("_", " ");

export function StatusBadge({ status }: { status: string }) {
  return <Badge tone={statusTone(status)}>{statusLabel(status)}</Badge>;
}

export function Alert({ tone = "info", children }: { tone?: "info" | "warning" | "error" | "success"; children: ReactNode }) {
  const map = {
    info: ["border-sky-200 bg-sky-50 text-sky-800", Info],
    warning: ["border-amber-200 bg-amber-50 text-amber-900", AlertTriangle],
    error: ["border-red-200 bg-red-50 text-red-800", XCircle],
    success: ["border-emerald-200 bg-emerald-50 text-emerald-800", CheckCircle2],
  } as const;
  const [style, Icon] = map[tone];
  return (
    <div role={tone === "error" ? "alert" : "status"} className={cx("flex gap-2.5 rounded-xl border px-3.5 py-2.5 text-sm", style)}>
      <Icon className="mt-0.5 size-4 shrink-0" aria-hidden />
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  );
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 py-6 text-sm text-slate-500">
      <Loader2 className="size-4 animate-spin" aria-hidden /> {label}
    </div>
  );
}

export function ErrorText({ error }: { error: unknown }) {
  if (!error) return null;
  return <Alert tone="error">{error instanceof Error ? error.message : String(error)}</Alert>;
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="rounded-xl border border-dashed border-slate-200 bg-slate-50/60 px-4 py-6 text-center text-sm text-slate-500">{children}</p>;
}

// ---------------------------------------------------------------- form controls

const inputClass =
  "w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 shadow-xs transition placeholder:text-slate-400 hover:border-slate-300 focus:border-indigo-500 focus:outline-none focus:ring-4 focus:ring-indigo-500/10 disabled:bg-slate-50";

export function Field({ label, hint, children, className }: { label: string; hint?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <label className={cx("block text-sm", className)}>
      <span className="mb-1.5 block font-medium text-slate-700">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-xs text-slate-500">{hint}</span>}
    </label>
  );
}

export function TextInput(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={cx(inputClass, props.className)} />;
}

export function TextArea(props: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea {...props} className={cx(inputClass, "font-[inherit]", props.className)} />;
}

export function Select(props: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return <select {...props} className={cx(inputClass, props.className)} />;
}

// The whole row is the tap target (44px tall), so it's easy to hit on a phone.
export function Checkbox({ label, checked, onChange, disabled }: { label: string; checked: boolean; onChange: (v: boolean) => void; disabled?: boolean }) {
  return (
    <label className={cx("flex min-h-11 cursor-pointer items-center gap-2.5 text-sm text-slate-700", disabled && "cursor-not-allowed opacity-60")}>
      <input type="checkbox" disabled={disabled} className="size-5 shrink-0 rounded border-slate-300 accent-indigo-600" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      {label}
    </label>
  );
}

/** Comma/newline separated list editor. */
export function ListInput({ value, onChange, rows = 2, placeholder }: { value: string[]; onChange: (v: string[]) => void; rows?: number; placeholder?: string }) {
  const [text, setText] = useState(value.join(", "));
  return (
    <TextArea
      rows={rows}
      value={text}
      placeholder={placeholder}
      onChange={(e) => {
        setText(e.target.value);
        onChange(e.target.value.split(/[,\n]/).map((s) => s.trim()).filter(Boolean));
      }}
    />
  );
}

export function NumberInput({ value, onChange, ...rest }: { value: number | null; onChange: (v: number | null) => void } & Omit<React.InputHTMLAttributes<HTMLInputElement>, "value" | "onChange">) {
  return (
    <TextInput
      type="number"
      {...rest}
      value={value ?? ""}
      onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))}
    />
  );
}

export function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  return (
    <div className="fixed inset-0 z-40 flex items-start justify-center overflow-y-auto bg-slate-900/40 p-4 backdrop-blur-sm" role="dialog" aria-modal="true" aria-label={title} onClick={onClose}>
      <div className="rise-in mt-10 w-full max-w-2xl rounded-2xl bg-white shadow-2xl ring-1 ring-slate-900/5" onClick={(e) => e.stopPropagation()}>
        <header className="flex items-center justify-between border-b border-slate-100 px-5 py-3.5">
          <h2 className="font-semibold tracking-tight text-slate-900">{title}</h2>
          <Button variant="ghost" onClick={onClose} aria-label="Close">
            ✕
          </Button>
        </header>
        <div className="p-5">{children}</div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- helpers

/** A mutation that refreshes every query when it succeeds; errors are kept for display. */
export function useAction<TArgs = void, TResult = unknown>(fn: (args: TArgs) => Promise<TResult>, onSuccess?: (r: TResult) => void) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: (result) => {
      client.invalidateQueries();
      onSuccess?.(result);
    },
  });
}

export function formatDate(value: string | null | undefined, withTime = false): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return withTime ? date.toLocaleString() : date.toLocaleDateString();
}

export function List({ items, empty = "None" }: { items: string[] | undefined; empty?: string }) {
  if (!items || items.length === 0) return <p className="text-sm text-slate-500">{empty}</p>;
  return (
    <ul className="list-disc space-y-1 pl-5 text-sm text-slate-700">
      {items.map((item, i) => (
        <li key={i}>{item}</li>
      ))}
    </ul>
  );
}

export function Pre({ children, className }: { children: ReactNode; className?: string }) {
  return <pre className={cx("scroll-soft max-h-[32rem] overflow-auto whitespace-pre-wrap break-words rounded-xl bg-slate-50 p-3 text-xs text-slate-800 ring-1 ring-slate-200", className)}>{children}</pre>;
}

export function JsonView({ value }: { value: unknown }) {
  return <Pre>{JSON.stringify(value, null, 2)}</Pre>;
}

export function Pager({ page, total, pageSize, onPage }: { page: number; total: number; pageSize: number; onPage: (p: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  return (
    <div className="mt-3 flex items-center justify-between text-sm text-slate-600">
      <span>
        {total} result{total === 1 ? "" : "s"} · page {page} of {pages}
      </span>
      <div className="flex gap-2">
        <Button disabled={page <= 1} onClick={() => onPage(page - 1)}>
          Previous
        </Button>
        <Button disabled={page >= pages} onClick={() => onPage(page + 1)}>
          Next
        </Button>
      </div>
    </div>
  );
}

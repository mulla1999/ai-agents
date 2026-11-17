// Structured parts of assistant messages. Everything is rendered as text by React: nothing from a
// job posting or a web page is ever inserted as HTML.

import { AlertTriangle, Briefcase, Check, CircleDashed, ExternalLink, Globe, MapPin, Paperclip, Send, Wallet, X } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import { Badge, Button, StatusBadge, cx, formatDate } from "../ui";
import type { ChatAction, ChatCard, ChatJob } from "./types";

const AVATAR_TONES = ["from-sky-400 to-indigo-500", "from-emerald-400 to-teal-600", "from-amber-400 to-orange-500", "from-fuchsia-400 to-violet-600", "from-rose-400 to-pink-600", "from-cyan-400 to-blue-600"];

function hostOf(url: string): string {
  try {
    return new URL(url).hostname;
  } catch {
    return url;
  }
}

function CompanyAvatar({ name }: { name: string }) {
  const hash = [...name].reduce((h, c) => (h * 31 + c.charCodeAt(0)) >>> 0, 7);
  const initials = name.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]?.toUpperCase()).join("") || "?";
  return <span className={cx("grid size-10 shrink-0 place-items-center rounded-xl bg-gradient-to-br text-sm font-semibold text-white", AVATAR_TONES[hash % AVATAR_TONES.length])}>{initials}</span>;
}

function ScoreRing({ score }: { score: number | null }) {
  if (score === null) return <span className="text-xs text-slate-400">not scored</span>;
  const tone = score >= 85 ? "text-emerald-500" : score >= 70 ? "text-indigo-500" : score >= 55 ? "text-amber-500" : "text-slate-400";
  const r = 16;
  const c = 2 * Math.PI * r;
  return (
    <span className="relative grid size-11 shrink-0 place-items-center" title={`Match score ${score}`}>
      <svg viewBox="0 0 40 40" className="absolute inset-0 -rotate-90" aria-hidden>
        <circle cx="20" cy="20" r={r} className="fill-none stroke-slate-100" strokeWidth="4" />
        <circle cx="20" cy="20" r={r} className={cx("fill-none stroke-current", tone)} strokeWidth="4" strokeLinecap="round" strokeDasharray={`${(score / 100) * c} ${c}`} />
      </svg>
      <span className="text-xs font-semibold text-slate-800">{score}</span>
    </span>
  );
}

function JobCard({ job, send, busy }: { job: ChatJob; send: (t: string) => void; busy: boolean }) {
  return (
    <article className="rounded-xl border border-slate-200 bg-white p-3.5 shadow-xs transition hover:border-indigo-200 hover:shadow-soft">
      <div className="flex gap-3">
        <CompanyAvatar name={job.company} />
        <div className="min-w-0 flex-1">
          <Link to={`/jobs/${job.id}`} className="line-clamp-2 font-semibold leading-snug text-slate-900 hover:text-indigo-700">
            {job.title}
          </Link>
          <p className="truncate text-sm text-slate-600">{job.company}</p>
        </div>
        <ScoreRing score={job.score} />
      </div>
      <div className="mt-2.5 flex flex-wrap gap-x-3 gap-y-1 text-xs text-slate-500">
        {job.location && (
          <span className="inline-flex items-center gap-1">
            <MapPin className="size-3.5" aria-hidden /> {job.location}
          </span>
        )}
        {job.work_mode && <span className="capitalize">{job.work_mode}</span>}
        {job.salary && (
          <span className="inline-flex items-center gap-1">
            <Wallet className="size-3.5" aria-hidden /> {job.salary}
          </span>
        )}
        {job.posted_at && <span>Posted {formatDate(job.posted_at)}</span>}
        <span className="text-slate-400">#{job.id}</span>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <StatusBadge status={job.status} />
        {job.suspicious && (
          <Badge tone="red">
            <AlertTriangle className="mr-1 size-3" aria-hidden /> review carefully
          </Badge>
        )}
        <span className="ml-auto flex gap-1.5">
          <Button variant="ghost" className="px-2.5 py-1 text-xs" disabled={busy} onClick={() => send(`Tell me about job #${job.id}`)}>
            Details
          </Button>
          <Button variant="primary" className="px-3 py-1 text-xs" disabled={busy} onClick={() => send(`Apply to job #${job.id}`)}>
            Apply
          </Button>
        </span>
      </div>
    </article>
  );
}

function Chips({ items, tone }: { items: string[]; tone: "green" | "amber" }) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {items.map((s) => (
        <Badge key={s} tone={tone}>
          {s}
        </Badge>
      ))}
    </div>
  );
}

function QuestionBox({ appId, q, send, busy }: { appId: number; q: { id: number; question: string; sensitive: boolean }; send: (t: string) => void; busy: boolean }) {
  const [value, setValue] = useState("");
  return (
    <form
      className="space-y-1.5"
      onSubmit={(e) => {
        e.preventDefault();
        if (value.trim()) send(`Answer question ${q.id} on application ${appId}: ${value.trim()}`);
        setValue("");
      }}
    >
      <label className="block text-sm text-slate-700">
        {q.question} {q.sensitive && <Badge tone="amber">sensitive</Badge>}
      </label>
      <div className="flex gap-2">
        <input
          value={value}
          onChange={(e) => setValue(e.target.value)}
          maxLength={1000}
          placeholder="Your answer"
          className="min-w-0 flex-1 rounded-lg border border-slate-200 px-3 py-1.5 text-sm focus:border-indigo-500 focus:outline-none focus:ring-4 focus:ring-indigo-500/10"
        />
        <Button type="submit" className="px-2.5" disabled={busy || !value.trim()} aria-label="Save answer">
          <Send className="size-4" />
        </Button>
      </div>
    </form>
  );
}

export function CardView({ card, send, busy }: { card: ChatCard; send: (t: string) => void; busy: boolean }) {
  switch (card.type) {
    case "jobs":
      return (
        <div className="grid gap-2.5">
          {card.items.map((j) => (
            <JobCard key={j.id} job={j} send={send} busy={busy} />
          ))}
        </div>
      );
    case "job":
      return (
        <div className="space-y-3">
          <JobCard job={card.job} send={send} busy={busy} />
          {card.recommendation && <p className="text-sm font-medium text-slate-800">{card.recommendation}</p>}
          {card.strong_skills.length > 0 && (
            <div>
              <p className="mb-1 text-xs font-medium uppercase tracking-wide text-slate-500">You match</p>
              <Chips items={card.strong_skills} tone="green" />
            </div>
          )}
          {card.gaps.length > 0 && (
            <div>
              <p className="mb-1 text-xs font-medium uppercase tracking-wide text-slate-500">Gaps</p>
              <Chips items={card.gaps} tone="amber" />
            </div>
          )}
          {card.description && <p className="line-clamp-5 whitespace-pre-line text-sm text-slate-600">{card.description}</p>}
        </div>
      );
    case "web_results":
      return (
        <ul className="divide-y divide-slate-100 overflow-hidden rounded-xl border border-slate-200 bg-white">
          {card.items.map((h) => (
            <li key={h.url} className="flex gap-3 p-3">
              <Globe className="mt-0.5 size-4 shrink-0 text-slate-400" aria-hidden />
              <div className="min-w-0 flex-1">
                <a href={h.url} target="_blank" rel="noopener noreferrer nofollow" className="line-clamp-1 text-sm font-medium text-slate-900 hover:text-indigo-700">
                  {h.title || h.url}
                </a>
                <p className="truncate text-xs text-emerald-700">{hostOf(h.url)}</p>
                {h.snippet && <p className="mt-0.5 line-clamp-2 text-xs text-slate-500">{h.snippet}</p>}
              </div>
              {h.fetchable ? (
                <Button className="self-center px-2.5 py-1 text-xs" disabled={busy} onClick={() => send(`Import ${h.url}`)}>
                  Import
                </Button>
              ) : (
                <span className="self-center text-xs text-slate-400" title="This site does not allow automated reading">
                  open it yourself
                </span>
              )}
            </li>
          ))}
        </ul>
      );
    case "application":
      return (
        <div className="space-y-3 rounded-xl border border-slate-200 bg-white p-3.5">
          <div className="flex flex-wrap items-center gap-2">
            <Briefcase className="size-4 text-slate-400" aria-hidden />
            <span className="font-medium text-slate-900">
              {card.title} · {card.company}
            </span>
            <StatusBadge status={card.status} />
            <Badge>via {card.route}</Badge>
          </div>
          {card.blockers.filter((b) => !b.startsWith("answer the question")).map((b) => (
            <p key={b} className="flex gap-1.5 text-sm text-amber-800">
              <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden /> {b}
            </p>
          ))}
          {card.questions.length > 0 && (
            <div className="space-y-3 border-t border-slate-100 pt-3">
              <p className="text-xs font-medium uppercase tracking-wide text-slate-500">Questions the employer asks</p>
              {card.questions.map((q) => (
                <QuestionBox key={q.id} appId={card.id} q={q} send={send} busy={busy} />
              ))}
            </div>
          )}
          <div className="flex gap-3 text-xs">
            <Link to="/queue" className="text-indigo-700 hover:underline">
              Open in Application Queue
            </Link>
            {card.route === "manual" && (
              <a href={card.apply_url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-indigo-700 hover:underline">
                Employer's application page <ExternalLink className="size-3" aria-hidden />
              </a>
            )}
          </div>
        </div>
      );
    case "email":
      return (
        <div className="overflow-hidden rounded-xl border border-slate-200 bg-white">
          <div className="space-y-0.5 border-b border-slate-100 bg-slate-50/70 px-3.5 py-2.5 text-sm">
            <p>
              <span className="text-slate-500">To:</span> {card.to}
            </p>
            <p>
              <span className="text-slate-500">Subject:</span> <span className="font-medium">{card.subject}</span>
            </p>
          </div>
          <p className="whitespace-pre-line px-3.5 py-3 text-sm leading-relaxed text-slate-700">{card.body}</p>
          <div className="flex items-center justify-between border-t border-slate-100 px-3.5 py-2 text-xs text-slate-500">
            <span className="inline-flex items-center gap-1">
              <Paperclip className="size-3.5" aria-hidden /> {card.attachment}
            </span>
            <Link to="/outreach" className="text-indigo-700 hover:underline">
              Edit in Outreach
            </Link>
          </div>
        </div>
      );
    case "applications":
      return (
        <ul className="divide-y divide-slate-100 overflow-hidden rounded-xl border border-slate-200 bg-white">
          {card.items.map((a) => (
            <li key={a.id} className="flex flex-wrap items-center gap-2 px-3.5 py-2.5 text-sm">
              <Link to={`/jobs/${a.job_id}`} className="min-w-0 flex-1 truncate font-medium text-slate-800 hover:text-indigo-700">
                {a.title} <span className="font-normal text-slate-500">· {a.company}</span>
              </Link>
              <StatusBadge status={a.status} />
              {a.needs_answers > 0 && <Badge tone="amber">{a.needs_answers} to answer</Badge>}
              {a.scheduled_for && <Badge tone="blue">sends {formatDate(a.scheduled_for, true)}</Badge>}
            </li>
          ))}
        </ul>
      );
    case "checklist":
      return (
        <ul className="space-y-1.5 rounded-xl border border-slate-200 bg-white p-3.5">
          {card.items.map((i) => (
            <li key={i.label} className="flex items-start gap-2 text-sm">
              {i.done ? <Check className="mt-0.5 size-4 shrink-0 text-emerald-500" aria-label="done" /> : <CircleDashed className="mt-0.5 size-4 shrink-0 text-amber-500" aria-label="missing" />}
              <span className={i.done ? "text-slate-500" : "text-slate-800"}>
                {i.label}
                {!i.done && <span className="text-slate-500"> — {i.how}</span>}
              </span>
            </li>
          ))}
        </ul>
      );
    case "fetched":
      return (
        <div className="rounded-xl border border-amber-200 bg-amber-50 p-3.5 text-sm text-amber-900">
          <p className="font-medium">{card.job.title || card.job.url}</p>
          <p>Missing: {card.job.missing.join(", ")}</p>
          <Link to="/jobs" className="mt-1 inline-block text-indigo-700 hover:underline">
            Open Jobs → Import job
          </Link>
        </div>
      );
  }
}

export function ActionCard({ action, onConfirm, onCancel, busy }: { action: ChatAction; onConfirm: () => void; onCancel: () => void; busy: boolean }) {
  const done = action.status === "done";
  return (
    <div className={cx("rounded-xl border p-3.5", action.status === "pending" ? "border-indigo-200 bg-indigo-50/60" : done ? "border-emerald-200 bg-emerald-50/60" : "border-slate-200 bg-slate-50")}>
      <p className="text-sm font-medium text-slate-900">{action.summary}</p>
      {action.status === "pending" ? (
        <div className="mt-2.5 flex gap-2">
          <Button variant="primary" busy={busy} onClick={onConfirm}>
            <Check className="size-4" aria-hidden /> Confirm
          </Button>
          <Button disabled={busy} onClick={onCancel}>
            <X className="size-4" aria-hidden /> Not now
          </Button>
        </div>
      ) : (
        <p className="mt-1 text-xs text-slate-600">
          {done ? "Done" : action.status === "running" ? "In progress…" : action.status === "failed" ? "Failed" : action.status === "expired" ? "Expired — ask again" : "Cancelled"}
          {action.result ? ` · ${action.result}` : ""}
        </p>
      )}
    </div>
  );
}

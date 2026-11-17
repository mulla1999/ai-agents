// Jobs toolbar: a search box with one Filters button, a row of quick toggles, then the count, active
// filters (removable chips) and sort. State lives in the URL, so a filtered view can be bookmarked or shared.

import { ArrowUpDown, Search, SlidersHorizontal, X } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { JOB_STATUSES, type Source } from "../api/types";
import { Button, Checkbox, Field, Select, TextInput, cx, statusLabel } from "./ui";

export const FILTER_KEYS = ["q", "company", "title", "location", "work_mode", "min_score", "max_score", "min_salary", "max_experience", "source", "status", "posted_after", "include_duplicates", "sort", "page"] as const;
export type FilterKey = (typeof FILTER_KEYS)[number];
export type FilterValues = Record<FilterKey, string>;

// Keys edited in the panel (draft until Apply); the rest change at once from the toolbar.
const PANEL_KEYS = ["company", "title", "location", "min_score", "max_score", "min_salary", "max_experience", "source", "status", "posted_after", "include_duplicates"] as const;
type PanelKey = (typeof PANEL_KEYS)[number];

const MODES = [
  { value: "remote", label: "Remote" },
  { value: "hybrid", label: "Hybrid" },
  { value: "onsite", label: "On-site" },
];
const POSTED = [
  { days: 1, label: "24 hours" },
  { days: 3, label: "3 days" },
  { days: 7, label: "7 days" },
  { days: 30, label: "30 days" },
];

function daysAgo(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() - days);
  return d.toISOString().slice(0, 10);
}

const label = (s: string) => statusLabel(s);

function Chip({ children, onRemove }: { children: ReactNode; onRemove: () => void }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-full border border-indigo-200 bg-indigo-50 py-0.5 pl-2.5 pr-1 text-xs font-medium text-indigo-800">
      <span>{children}</span>
      <button type="button" onClick={onRemove} aria-label="Remove filter" className="grid size-4 place-items-center rounded-full text-indigo-400 hover:bg-indigo-100 hover:text-indigo-700">
        <X className="size-3" />
      </button>
    </span>
  );
}

function Toggle({ active, onClick, children }: { active: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={cx(
        "shrink-0 whitespace-nowrap rounded-full border px-3.5 py-1.5 text-sm font-medium transition",
        active ? "border-indigo-500 bg-indigo-600 text-white shadow-sm" : "border-slate-200 bg-white text-slate-600 hover:border-slate-300 hover:bg-slate-50",
      )}
    >
      {children}
    </button>
  );
}

export function JobFilters({
  values,
  total,
  sources,
  onChange,
  onClear,
}: {
  values: FilterValues;
  total: number | undefined;
  sources: Source[];
  onChange: (patch: Partial<FilterValues>) => void;
  onClear: () => void;
}) {
  const [query, setQuery] = useState(values.q);
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<Record<PanelKey, string>>(() => pick(values));
  const panel = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);

  // Search as you type (debounced); the URL stays the source of truth.
  useEffect(() => {
    setQuery(values.q);
  }, [values.q]);
  useEffect(() => {
    if (query === values.q) return;
    const t = setTimeout(() => onChange({ q: query.trim() }), 350);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query]);

  useEffect(() => {
    if (!open) return;
    setDraft(pick(values));
    const close = (e: MouseEvent) => {
      if (!panel.current?.contains(e.target as Node) && !button.current?.contains(e.target as Node)) setOpen(false);
    };
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", esc);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const statuses = values.status ? values.status.split(",") : [];
  const draftStatuses = draft.status ? draft.status.split(",") : [];
  const panelCount = PANEL_KEYS.filter((k) => values[k]).length;
  const postedPreset = POSTED.find((p) => values.posted_after === daysAgo(p.days));
  const sourceName = (key: string) => sources.find((s) => s.key === key)?.name ?? key;
  const setD = (k: PanelKey, v: string) => setDraft((d) => ({ ...d, [k]: v }));

  const chips: { key: string; text: string; clear: Partial<FilterValues> }[] = [];
  if (values.q) chips.push({ key: "q", text: `“${values.q}”`, clear: { q: "" } });
  if (values.company) chips.push({ key: "company", text: `Company: ${values.company}`, clear: { company: "" } });
  if (values.title) chips.push({ key: "title", text: `Title: ${values.title}`, clear: { title: "" } });
  if (values.location) chips.push({ key: "location", text: `Location: ${values.location}`, clear: { location: "" } });
  if (values.work_mode) chips.push({ key: "work_mode", text: label(MODES.find((m) => m.value === values.work_mode)?.label ?? values.work_mode), clear: { work_mode: "" } });
  if (values.min_score || values.max_score)
    chips.push({ key: "score", text: `Score ${values.min_score || 0}–${values.max_score || 100}`, clear: { min_score: "", max_score: "" } });
  if (values.min_salary) chips.push({ key: "min_salary", text: `≥ ${values.min_salary} LPA`, clear: { min_salary: "" } });
  if (values.max_experience) chips.push({ key: "max_experience", text: `≤ ${values.max_experience} yrs required`, clear: { max_experience: "" } });
  if (values.source) chips.push({ key: "source", text: `Source: ${sourceName(values.source)}`, clear: { source: "" } });
  statuses.forEach((s) => chips.push({ key: `status-${s}`, text: label(s), clear: { status: statuses.filter((x) => x !== s).join(",") } }));
  if (values.posted_after) chips.push({ key: "posted", text: postedPreset ? `Posted in ${postedPreset.label}` : `Posted after ${values.posted_after}`, clear: { posted_after: "" } });
  if (values.include_duplicates) chips.push({ key: "dups", text: "Including duplicates", clear: { include_duplicates: "" } });

  return (
    <div className="relative mb-4 space-y-3">
      {/* 1. Search, and everything else behind one Filters button. */}
      <div className="flex items-center gap-2">
        <label className="relative min-w-0 flex-1">
          <span className="sr-only">Search jobs</span>
          <Search className="pointer-events-none absolute left-3.5 top-1/2 size-4 -translate-y-1/2 text-slate-400" aria-hidden />
          <input
            type="search"
            value={query}
            maxLength={120}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && onChange({ q: query.trim() })}
            placeholder="Search jobs, companies or skills"
            className="w-full rounded-xl border border-slate-200 bg-white py-2.5 pl-10 pr-3 text-sm text-slate-900 shadow-xs placeholder:text-slate-400 transition focus:border-indigo-500 focus:outline-none focus:ring-4 focus:ring-indigo-500/10"
          />
        </label>
        <div className="sm:relative">
          <button
            ref={button}
            type="button"
            aria-expanded={open}
            aria-haspopup="dialog"
            onClick={() => setOpen(!open)}
            className={cx(
              "inline-flex h-[2.625rem] items-center gap-1.5 rounded-xl border px-3.5 text-sm font-medium shadow-xs transition",
              open || panelCount ? "border-indigo-300 bg-indigo-50 text-indigo-700" : "border-slate-200 bg-white text-slate-700 hover:bg-slate-50",
            )}
          >
            <SlidersHorizontal className="size-4" aria-hidden /> Filters
            {panelCount > 0 && <span className="grid size-5 place-items-center rounded-full bg-indigo-600 text-[0.6875rem] text-white">{panelCount}</span>}
          </button>
              {open && (
                <div
                  ref={panel}
                  role="dialog"
                  aria-label="Filters"
                  className="rise-in fixed inset-x-3 top-20 z-30 max-h-[calc(100vh-6rem)] overflow-y-auto rounded-2xl bg-white p-4 shadow-2xl ring-1 ring-slate-900/10 sm:absolute sm:inset-x-auto sm:right-0 sm:top-full sm:mt-2 sm:w-[34rem]"
                >
                  <div className="grid gap-3 sm:grid-cols-2">
                    <Field label="Company">
                      <TextInput value={draft.company} maxLength={100} placeholder="e.g. Barclays" onChange={(e) => setD("company", e.target.value)} />
                    </Field>
                    <Field label="Job title">
                      <TextInput value={draft.title} maxLength={100} placeholder="e.g. Backend" onChange={(e) => setD("title", e.target.value)} />
                    </Field>
                    <Field label="Location">
                      <TextInput value={draft.location} maxLength={80} placeholder="e.g. Pune" onChange={(e) => setD("location", e.target.value)} />
                    </Field>
                    <Field label="Source">
                      <Select value={draft.source} onChange={(e) => setD("source", e.target.value)}>
                        <option value="">Any source</option>
                        {sources.filter((s) => s.support !== "unsupported").map((s) => (
                          <option key={s.key} value={s.key}>
                            {s.name}
                          </option>
                        ))}
                      </Select>
                    </Field>
                    <Field label="Match score">
                      <div className="flex items-center gap-2">
                        <TextInput type="number" aria-label="Minimum score" min={0} max={100} placeholder="0" value={draft.min_score} onChange={(e) => setD("min_score", e.target.value)} />
                        <span className="text-slate-400">–</span>
                        <TextInput type="number" aria-label="Maximum score" min={0} max={100} placeholder="100" value={draft.max_score} onChange={(e) => setD("max_score", e.target.value)} />
                      </div>
                    </Field>
                    <div className="grid grid-cols-2 gap-2">
                      <Field label="Min salary (LPA)">
                        <TextInput type="number" min={0} max={500} step="0.5" value={draft.min_salary} onChange={(e) => setD("min_salary", e.target.value)} />
                      </Field>
                      <Field label="Max years req.">
                        <TextInput type="number" min={0} max={40} value={draft.max_experience} onChange={(e) => setD("max_experience", e.target.value)} />
                      </Field>
                    </div>
                    <Field label="Posted">
                      <Select
                        value={POSTED.find((p) => draft.posted_after === daysAgo(p.days))?.days.toString() ?? (draft.posted_after ? "custom" : "")}
                        onChange={(e) => setD("posted_after", e.target.value && e.target.value !== "custom" ? daysAgo(Number(e.target.value)) : "")}
                      >
                        <option value="">Any time</option>
                        {POSTED.map((p) => (
                          <option key={p.days} value={p.days}>
                            In the last {p.label}
                          </option>
                        ))}
                        {draft.posted_after && !POSTED.some((p) => draft.posted_after === daysAgo(p.days)) && <option value="custom">After {draft.posted_after}</option>}
                      </Select>
                    </Field>
                    <div className="flex items-end pb-2">
                      <Checkbox label="Show duplicates" checked={draft.include_duplicates === "true"} onChange={(v) => setD("include_duplicates", v ? "true" : "")} />
                    </div>
                  </div>
                  <fieldset className="mt-4">
                    <legend className="mb-2 text-sm font-medium text-slate-700">Status</legend>
                    <div className="grid grid-cols-2 gap-x-3 gap-y-1.5 sm:grid-cols-3">
                      {JOB_STATUSES.map((s) => (
                        <Checkbox
                          key={s}
                          label={label(s)}
                          checked={draftStatuses.includes(s)}
                          onChange={(v) => setD("status", (v ? [...draftStatuses, s] : draftStatuses.filter((x) => x !== s)).join(","))}
                        />
                      ))}
                    </div>
                  </fieldset>
                  {problem(draft) && <p role="alert" className="mt-3 text-xs text-red-600">{problem(draft)}</p>}
                  <div className="mt-4 flex items-center justify-between border-t border-slate-100 pt-3">
                    <Button variant="ghost" onClick={() => setDraft(Object.fromEntries(PANEL_KEYS.map((k) => [k, ""])) as Record<PanelKey, string>)}>
                      Reset
                    </Button>
                    <div className="flex gap-2">
                      <Button onClick={() => setOpen(false)}>Cancel</Button>
                      <Button
                        variant="primary"
                        disabled={!!problem(draft)}
                        onClick={() => {
                          onChange(Object.fromEntries(PANEL_KEYS.map((k) => [k, draft[k].trim()])));
                          setOpen(false);
                        }}
                      >
                        Show results
                      </Button>
                    </div>
                  </div>
                </div>
              )}
        </div>
      </div>

      {/* 2. The few choices people use most, one tap each (scrolls sideways on small phones). */}
      <div className="scroll-soft -mx-1 flex gap-2 overflow-x-auto px-1 pb-1">
        <Toggle active={values.min_score === "85"} onClick={() => onChange({ min_score: values.min_score === "85" ? "" : "85" })}>
          Top matches
        </Toggle>
        {MODES.map((m) => (
          <Toggle key={m.value} active={values.work_mode === m.value} onClick={() => onChange({ work_mode: values.work_mode === m.value ? "" : m.value })}>
            {m.label}
          </Toggle>
        ))}
        <Toggle active={postedPreset?.days === 7} onClick={() => onChange({ posted_after: postedPreset?.days === 7 ? "" : daysAgo(7) })}>
          Posted this week
        </Toggle>
      </div>

      {/* 3. How many, what is applied, and the order. */}
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1.5 border-b border-slate-200/70 pb-2.5">
        {total !== undefined && (
          <span className="text-sm font-medium text-slate-700">
            {total.toLocaleString()} job{total === 1 ? "" : "s"}
          </span>
        )}
        {chips.map((c) => (
          <Chip key={c.key} onRemove={() => onChange(c.clear)}>
            {c.text}
          </Chip>
        ))}
        {chips.length > 0 && (
          <button type="button" onClick={onClear} className="text-xs font-medium text-slate-500 hover:text-indigo-700">
            Clear all
          </button>
        )}
        <label className="ml-auto inline-flex items-center gap-1 text-sm text-slate-500">
          <ArrowUpDown className="size-3.5" aria-hidden />
          <span className="sr-only">Sort by</span>
          <select
            value={values.sort || "score"}
            onChange={(e) => onChange({ sort: e.target.value === "score" ? "" : e.target.value })}
            className="cursor-pointer rounded-md bg-transparent py-1 pr-1 text-sm font-medium text-slate-700 hover:text-indigo-700 focus:outline-none focus:ring-2 focus:ring-indigo-500/30"
          >
            <option value="score">Best match</option>
            <option value="recent">Newest found</option>
            <option value="posted">Newest posted</option>
          </select>
        </label>
      </div>
    </div>
  );
}

function pick(values: FilterValues): Record<PanelKey, string> {
  return Object.fromEntries(PANEL_KEYS.map((k) => [k, values[k]])) as Record<PanelKey, string>;
}

/** The same limits the API enforces, shown before the request. */
function problem(d: Record<PanelKey, string>): string | null {
  const n = (v: string) => (v === "" ? null : Number(v));
  const lo = n(d.min_score);
  const hi = n(d.max_score);
  if ((lo !== null && (lo < 0 || lo > 100)) || (hi !== null && (hi < 0 || hi > 100))) return "Scores are from 0 to 100.";
  if (lo !== null && hi !== null && lo > hi) return "The minimum score is above the maximum.";
  const sal = n(d.min_salary);
  if (sal !== null && (sal < 0 || sal > 500)) return "Salary is in lakhs per annum (LPA), e.g. 25 — not rupees.";
  const exp = n(d.max_experience);
  if (exp !== null && (exp < 0 || exp > 40)) return "Years required must be between 0 and 40.";
  return null;
}

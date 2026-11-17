// Resume Builder: write or edit a resume on the site, with a live health check, optional AI help on each
// bullet and the summary, a PDF preview, and Save (it becomes the resume HireFinch matches and tailors from).
// The draft autosaves in this browser so nothing is lost on a reload.

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowLeft, ArrowUp, Eye, FileUp, Plus, RefreshCw, Sparkles, Trash2, Wand2 } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router";
import { api, apiBlob } from "../api/client";
import type { Bullet, MasterResume, ResumeDocument } from "../api/types";
import { Alert, Badge, Button, Card, Checkbox, Collapsible, ErrorText, Field, ListInput, PageHeader, TextArea, TextInput, cx, useAction } from "../components/ui";

type Doc = ResumeDocument;
type Entry = Doc["experience"][number];
type Project = Doc["projects"][number];
interface Tip {
  level: "fix" | "improve";
  section: string;
  message: string;
  target: string | null;
  kind?: string | null;
}

/** The same problem on several bullets, shown once with a count ("Leave out I/my/we · 4 bullets"). */
function groupTips(tips: Tip[]): { tip: Tip; targets: string[] }[] {
  const groups = new Map<string, { tip: Tip; targets: string[] }>();
  for (const t of tips) {
    const key = `${t.level}:${t.kind ?? t.message}`;
    const g = groups.get(key) ?? { tip: t, targets: [] };
    if (t.target) g.targets.push(t.target);
    groups.set(key, g);
  }
  return [...groups.values()];
}
interface Suggestion {
  text: string;
  question: string;
  rejected: string;
}

const DRAFT_KEY = "hirefinch:resume-builder";
const uid = () => Math.random().toString(36).slice(2, 9);

const EMPTY: Doc = {
  contact: { name: "", headline: null, email: null, phone: null, location: null, links: [] },
  summary: "",
  skills: [{ name: "Skills", items: [] }],
  experience: [],
  projects: [],
  education: [],
  certifications: [],
  extra_sections: [],
  warnings: [],
};
const newEntry = (): Entry => ({
  id: uid(), title: "", company: "", location: null, start: null, end: null, is_current: false, date_text: "", is_internship: false,
  bullets: [{ id: uid(), text: "" }],
});
const newProject = (): Project => ({ id: uid(), name: "", subtitle: null, technologies: [], bullets: [{ id: uid(), text: "" }] });

// A draft remembers which resume it started from, so the page can say so and notice when the resume
// in use changes.
interface Source {
  masterId: number | null;
  filename: string;
  loadedAt: string;
}
interface Draft {
  doc: Doc;
  source: Source;
}

function loadDraft(): Draft | null {
  try {
    const raw = localStorage.getItem(DRAFT_KEY);
    if (!raw) return null;
    const data = JSON.parse(raw);
    // Drafts saved before sources were tracked held just the resume.
    return data && "doc" in data ? (data as Draft) : { doc: data as Doc, source: { masterId: null, filename: "", loadedAt: "" } };
  } catch {
    return null;
  }
}

function saveDraft(draft: Draft | null) {
  try {
    if (draft) localStorage.setItem(DRAFT_KEY, JSON.stringify(draft));
    else localStorage.removeItem(DRAFT_KEY);
  } catch {
    /* private mode: the draft just isn't kept */
  }
}

// "2021-06-01" <-> the "2021-06" a month picker uses.
const toMonth = (d: string | null) => (d ? d.slice(0, 7) : "");
const fromMonth = (m: string) => (m ? `${m}-01` : null);

export function ResumeBuilderPage() {
  const [draft, setDraft] = useState<Draft | null>(() => loadDraft());
  const [choosing, setChoosing] = useState(false);
  useEffect(() => saveDraft(draft), [draft]);
  if (!draft || choosing) {
    return (
      <Chooser
        hasDraft={!!draft}
        onPick={(d) => {
          setDraft(d);
          setChoosing(false);
        }}
        onBack={draft ? () => setChoosing(false) : undefined}
      />
    );
  }
  return (
    <Editor
      draft={draft}
      setDoc={(doc) => setDraft({ ...draft, doc })}
      setDraft={setDraft}
      onChooseSource={() => setChoosing(true)}
    />
  );
}

const now = () => new Date().toISOString();

/** Pick what to work on: any uploaded resume (the one in use first) or a blank page. */
function Chooser({ hasDraft, onPick, onBack }: { hasDraft: boolean; onPick: (d: Draft) => void; onBack?: () => void }) {
  const masters = useQuery({ queryKey: ["masters"], queryFn: () => api<MasterResume[]>("/resumes/masters") });
  const list = [...(masters.data ?? [])].sort((a, b) => Number(b.is_active) - Number(a.is_active));
  const load = useAction(
    (m: MasterResume) => api<{ document: Doc }>(`/resumes/masters/${m.id}`).then((r) => ({ r, m })),
    ({ r, m }) => onPick({ doc: { ...EMPTY, ...r.document, warnings: [] }, source: { masterId: m.id, filename: m.filename, loadedAt: now() } }),
  );
  const confirmed = () => !hasDraft || window.confirm("This replaces your current draft. Continue?");
  return (
    <>
      <PageHeader
        title="Resume Builder"
        subtitle="Pick what to work on. When you save, the result becomes the resume HireFinch uses for matching and tailoring."
        actions={
          onBack && (
            <Button onClick={onBack}>
              <ArrowLeft className="size-4" aria-hidden /> Back to my draft
            </Button>
          )
        }
      />
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_20rem]">
        <Card title="Start from one of your resumes">
          {masters.isLoading ? (
            <p className="text-sm text-slate-500">Loading…</p>
          ) : list.length === 0 ? (
            <p className="text-sm text-slate-600">
              No resume uploaded yet.{" "}
              <Link className="text-indigo-700 hover:underline" to="/profile">
                Upload one in Profile
              </Link>
              , or start blank.
            </p>
          ) : (
            <ul className="divide-y divide-slate-100">
              {list.map((m) => (
                <li key={m.id} className="flex flex-wrap items-center gap-2 py-3">
                  <div className="min-w-0 flex-1">
                    <p className="flex flex-wrap items-center gap-1.5 font-medium text-slate-900">
                      <span className="break-all">{m.filename}</span>
                      {m.is_active && <Badge tone="green">in use</Badge>}
                    </p>
                    <p className="text-xs text-slate-500">
                      {new Date(m.uploaded_at).toLocaleDateString()} · {m.experience_count} roles · {m.skills_count} skills
                    </p>
                  </div>
                  <Button variant={m.is_active ? "primary" : "secondary"} busy={load.isPending && load.variables?.id === m.id} onClick={() => confirmed() && load.mutate(m)}>
                    <FileUp className="size-4" aria-hidden /> Use this
                  </Button>
                </li>
              ))}
            </ul>
          )}
          <ErrorText error={load.error || masters.error} />
        </Card>
        <Card title="Start from scratch">
          <p className="mb-3 text-sm text-slate-600">No resume yet? Fill in each part step by step; it takes about 15 minutes.</p>
          <Button
            onClick={() => confirmed() && onPick({ doc: { ...EMPTY, experience: [newEntry()] }, source: { masterId: null, filename: "", loadedAt: now() } })}
          >
            <Plus className="size-4" aria-hidden /> Start blank
          </Button>
        </Card>
      </div>
    </>
  );
}

/** Where this draft came from, and a nudge when the resume in use has changed since. */
function SourceBar({ draft, onChange, onLoadActive }: { draft: Draft; onChange: () => void; onLoadActive: (m: MasterResume) => void }) {
  const masters = useQuery({ queryKey: ["masters"], queryFn: () => api<MasterResume[]>("/resumes/masters") });
  const active = masters.data?.find((m) => m.is_active);
  const [dismissed, setDismissed] = useState<number | null>(null);
  const stale = active && draft.source.masterId !== null && active.id !== draft.source.masterId && dismissed !== active.id;
  return (
    <div className="mb-4 space-y-2">
      <div className="flex flex-wrap items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm shadow-xs">
        <span className="min-w-0 flex-1 text-slate-600">
          {draft.source.filename ? (
            <>
              Draft from <b className="break-all text-slate-900">{draft.source.filename}</b>
            </>
          ) : draft.source.loadedAt ? (
            "Draft started from scratch"
          ) : (
            "Draft from an earlier session"
          )}
          {draft.source.loadedAt && <span className="text-slate-400"> · {new Date(draft.source.loadedAt).toLocaleString()}</span>}
        </span>
        <Button className="py-1" onClick={onChange}>
          Change
        </Button>
      </div>
      {stale && (
        <Alert tone="info">
          Your resume in use is now <b>{active.filename}</b>, not the one this draft came from.{" "}
          <button type="button" className="font-medium underline" onClick={() => window.confirm("Replace your draft with it?") && onLoadActive(active)}>
            Load it here
          </button>{" "}
          ·{" "}
          <button type="button" className="underline" onClick={() => setDismissed(active.id)}>
            Keep my draft
          </button>
        </Alert>
      )}
    </div>
  );
}

function Editor({ draft, setDoc, setDraft, onChooseSource }: { draft: Draft; setDoc: (d: Doc) => void; setDraft: (d: Draft) => void; onChooseSource: () => void }) {
  const doc = draft.doc;
  const client = useQueryClient();
  const loadActive = useAction(
    (m: MasterResume) => api<{ document: Doc }>(`/resumes/masters/${m.id}`).then((r) => ({ r, m })),
    ({ r, m }) => setDraft({ doc: { ...EMPTY, ...r.document, warnings: [] }, source: { masterId: m.id, filename: m.filename, loadedAt: now() } }),
  );
  const status = useQuery({ queryKey: ["assistant-status"], queryFn: () => api<{ ai: boolean }>("/assistant/status"), staleTime: 60_000 });
  const ai = !!status.data?.ai;
  const [tips, setTips] = useState<{ score: number; tips: Tip[] } | null>(null);
  const [ats, setAts] = useState<AtsResult | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const patch = (p: Partial<Doc>) => setDoc({ ...doc, ...p });

  // Health check as you type (debounced). It is rule-based and free, so it can run often.
  useEffect(() => {
    const t = setTimeout(() => {
      api<{ score: number; tips: Tip[] }>("/resume-builder/review", { body: doc }).then(setTips, () => undefined);
    }, 700);
    return () => clearTimeout(t);
  }, [doc]);
  useEffect(() => () => void (preview && URL.revokeObjectURL(preview)), [preview]);

  const showPreview = useAction(
    () => apiBlob("/resume-builder/preview", doc),
    (blob) => {
      const url = URL.createObjectURL(blob);
      if (window.matchMedia("(min-width: 1024px)").matches) setPreview(url);
      else window.open(url, "_blank", "noopener");
    },
  );
  const save = useAction(() => api<MasterResume>("/resume-builder/save", { method: "POST", body: doc }), (m) => {
    // The saved resume is now the one in use, and this draft's source.
    setDraft({ doc, source: { masterId: m.id, filename: m.filename, loadedAt: now() } });
    void client.invalidateQueries();
  });

  return (
    <>
      <PageHeader
        title="Resume Builder"
        subtitle="Your draft saves in this browser as you type. Save it to make it the resume HireFinch uses."
      />
      <SourceBar draft={draft} onChange={onChooseSource} onLoadActive={(m) => loadActive.mutate(m)} />
      <ErrorText error={loadActive.error} />
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_20rem]">
        <div className="order-2 min-w-0 space-y-4 lg:order-1">
          <Collapsible defaultOpen summary={doc.contact.name || "Name, email, phone and links"}>
            <Card title="1. Contact details">
              <div className="grid gap-3 sm:grid-cols-2">
                <Field label="Full name">
                  <TextInput value={doc.contact.name} onChange={(e) => patch({ contact: { ...doc.contact, name: e.target.value } })} />
                </Field>
                <Field label="Current role" hint="e.g. Full Stack Developer">
                  <TextInput value={doc.contact.headline ?? ""} onChange={(e) => patch({ contact: { ...doc.contact, headline: e.target.value || null } })} />
                </Field>
                <Field label="Email">
                  <TextInput type="email" value={doc.contact.email ?? ""} onChange={(e) => patch({ contact: { ...doc.contact, email: e.target.value || null } })} />
                </Field>
                <Field label="Phone">
                  <TextInput type="tel" value={doc.contact.phone ?? ""} onChange={(e) => patch({ contact: { ...doc.contact, phone: e.target.value || null } })} />
                </Field>
                <Field label="City">
                  <TextInput value={doc.contact.location ?? ""} onChange={(e) => patch({ contact: { ...doc.contact, location: e.target.value || null } })} />
                </Field>
                <Field label="Links" hint="LinkedIn, GitHub or portfolio, separated by commas">
                  <ListInput rows={1} value={doc.contact.links} onChange={(links) => patch({ contact: { ...doc.contact, links } })} />
                </Field>
              </div>
            </Card>
          </Collapsible>

          <Collapsible summary={doc.summary ? `${doc.summary.split(/\s+/).length} words` : "2–3 sentences about who you are professionally"}>
            <Card title="2. Summary">
              <SummaryEditor doc={doc} ai={ai} onChange={(summary) => patch({ summary })} />
            </Card>
          </Collapsible>

          <Collapsible defaultOpen summary={`${doc.experience.length} job${doc.experience.length === 1 ? "" : "s"}`}>
            <Card title="3. Work experience">
              <div className="space-y-5">
                {doc.experience.map((e, i) => (
                  <ExperienceEditor
                    key={e.id}
                    entry={e}
                    ai={ai}
                    onChange={(next) => patch({ experience: doc.experience.map((x) => (x.id === e.id ? next : x)) })}
                    onRemove={() => window.confirm("Remove this job?") && patch({ experience: doc.experience.filter((x) => x.id !== e.id) })}
                    onMove={(d) => patch({ experience: move(doc.experience, i, d) })}
                  />
                ))}
                <Button onClick={() => patch({ experience: [...doc.experience, newEntry()] })}>
                  <Plus className="size-4" aria-hidden /> Add a job
                </Button>
              </div>
            </Card>
          </Collapsible>

          <Collapsible summary={doc.projects.length ? `${doc.projects.length} project${doc.projects.length === 1 ? "" : "s"}` : "Optional: great if you're starting out"}>
            <Card title="4. Projects">
              <div className="space-y-5">
                {doc.projects.map((p, i) => (
                  <ProjectEditor
                    key={p.id}
                    project={p}
                    ai={ai}
                    onChange={(next) => patch({ projects: doc.projects.map((x) => (x.id === p.id ? next : x)) })}
                    onRemove={() => patch({ projects: doc.projects.filter((x) => x.id !== p.id) })}
                    onMove={(d) => patch({ projects: move(doc.projects, i, d) })}
                  />
                ))}
                <Button onClick={() => patch({ projects: [...doc.projects, newProject()] })}>
                  <Plus className="size-4" aria-hidden /> Add a project
                </Button>
              </div>
            </Card>
          </Collapsible>

          <Collapsible summary={`${doc.skills.reduce((n, g) => n + g.items.length, 0)} skills`}>
            <Card title="5. Skills">
              <p className="mb-3 text-sm text-slate-600">Group them (e.g. Languages, Frameworks, Cloud). Only list what you could talk about in an interview.</p>
              <div className="space-y-3">
                {doc.skills.map((g, i) => (
                  <div key={i} className="grid gap-2 sm:grid-cols-[12rem_minmax(0,1fr)_auto] sm:items-start">
                    <TextInput aria-label="Group name" value={g.name} onChange={(e) => patch({ skills: doc.skills.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)) })} />
                    <ListInput rows={2} placeholder="Java, Spring Boot, React…" value={g.items} onChange={(items) => patch({ skills: doc.skills.map((x, j) => (j === i ? { ...x, items } : x)) })} />
                    <Button variant="ghost" aria-label="Remove group" onClick={() => patch({ skills: doc.skills.filter((_, j) => j !== i) })}>
                      <Trash2 className="size-4" />
                    </Button>
                  </div>
                ))}
                <Button onClick={() => patch({ skills: [...doc.skills, { name: "", items: [] }] })}>
                  <Plus className="size-4" aria-hidden /> Add a group
                </Button>
              </div>
            </Card>
          </Collapsible>

          <Collapsible summary={doc.education.length ? doc.education[0] : "Degree, college, year"}>
            <Card title="6. Education and certifications">
              <div className="grid gap-3">
                <Field label="Education" hint="One per line, e.g. B.E. Computer Engineering, Pune University, 2021">
                  <LinesInput value={doc.education} onChange={(education) => patch({ education })} />
                </Field>
                <Field label="Certifications (optional)" hint="One per line">
                  <LinesInput value={doc.certifications} onChange={(certifications) => patch({ certifications })} />
                </Field>
              </div>
            </Card>
          </Collapsible>
        </div>

        {/* Phones: the score and Save come first, so they are not 10 screens down. */}
        <aside className="order-1 space-y-4 lg:sticky lg:top-4 lg:order-2 lg:self-start">
          <Verdict ats={ats} report={tips} />
          <AtsCard doc={doc} onChange={setDoc} onResult={setAts} />
          <HealthCard report={tips} doc={doc} ai={ai} onApply={setDoc} />
          <Card>
            <div className="space-y-2">
              <Button className="w-full" busy={showPreview.isPending} onClick={() => showPreview.mutate()}>
                <Eye className="size-4" aria-hidden /> Preview PDF
              </Button>
              <Button className="w-full" variant="primary" busy={save.isPending} onClick={() => save.mutate()}>
                Save as my resume
              </Button>
              <ErrorText error={showPreview.error || save.error} />
              {save.isSuccess && (
                <Alert tone="success">
                  Saved as “{save.data!.filename}” and now in use. New matches and tailored resumes start from it.{" "}
                  <Link className="underline" to="/profile">
                    See it in Profile
                  </Link>
                </Alert>
              )}
              {!ai && (
                <p className="text-xs text-slate-500">
                  Writing help needs an AI connection:{" "}
                  <Link className="text-indigo-700 hover:underline" to="/integrations">
                    connect one free
                  </Link>
                  .
                </p>
              )}
            </div>
          </Card>
        </aside>
      </div>
      {preview && (
        <div className="fixed inset-0 z-50 flex flex-col bg-slate-950/70 p-4" role="dialog" aria-label="Resume preview">
          <div className="mx-auto flex h-full w-full max-w-4xl flex-col overflow-hidden rounded-2xl bg-white">
            <div className="flex items-center justify-between border-b border-slate-100 px-4 py-2">
              <span className="text-sm font-medium">Preview</span>
              <Button variant="ghost" onClick={() => setPreview(null)}>
                Close
              </Button>
            </div>
            <iframe title="Resume preview" src={preview} className="min-h-0 flex-1" />
          </div>
        </div>
      )}
    </>
  );
}

function move<T>(list: T[], i: number, d: -1 | 1): T[] {
  const j = i + d;
  if (j < 0 || j >= list.length) return list;
  const next = [...list];
  [next[i], next[j]] = [next[j], next[i]];
  return next;
}

function LinesInput({ value, onChange }: { value: string[]; onChange: (v: string[]) => void }) {
  const [text, setText] = useState(value.join("\n"));
  return (
    <TextArea
      rows={Math.max(2, value.length + 1)}
      value={text}
      onChange={(e) => {
        setText(e.target.value);
        onChange(e.target.value.split("\n").map((l) => l.trim()).filter(Boolean));
      }}
    />
  );
}

interface FixChange {
  op: "bullet" | "remove" | "summary" | "skills";
  section: string;
  id?: string;
  before: string;
  after: string;
  groups?: Doc["skills"];
}
interface FixResult {
  document: Doc;
  changes: FixChange[];
  score_before: number;
  score_after: number;
  remaining: Tip[];
  note: string;
}

const CHANGE_LABEL: Record<FixChange["op"], string> = { skills: "Skills section", bullet: "Bullet reworded", summary: "Summary", remove: "Remove bullet" };

// Apply only the changes the person kept ticked, to the resume as it is now.
function applyChanges(doc: Doc, changes: FixChange[]): Doc {
  const next: Doc = structuredClone(doc);
  const entries = [...next.experience, ...next.projects];
  for (const c of changes) {
    if (c.op === "summary") next.summary = c.after;
    else if (c.op === "skills" && c.groups) next.skills = c.groups;
    else if (c.op === "bullet") entries.forEach((e) => e.bullets.forEach((b) => b.id === c.id && (b.text = c.after)));
    else if (c.op === "remove") entries.forEach((e) => (e.bullets = e.bullets.filter((b) => b.id !== c.id)));
  }
  return next;
}

function HealthCard({ report, doc, ai, onApply }: { report: { score: number; tips: Tip[] } | null; doc: Doc; ai: boolean; onApply: (d: Doc) => void }) {
  const [all, setAll] = useState(false);
  const fix = useAction(() => api<FixResult>("/resume-builder/fix-all", { method: "POST", body: doc }));
  if (!report) return null;
  const tone = report.score >= 85 ? "text-emerald-700" : report.score >= 65 ? "text-amber-700" : "text-red-700";
  const groups = groupTips(report.tips);
  const shown = all ? groups : groups.slice(0, 5);
  return (
    <Card title="Recruiter readiness">
      <p className="-mt-1 mb-2 text-xs text-slate-500">How a person reading it will judge the writing. These don't stop an ATS reading your resume.</p>
      <div className="mb-3 flex items-baseline gap-2">
        <span className={cx("text-3xl font-semibold tabular-nums", tone)}>{report.score}</span>
        <span className="text-sm text-slate-500">/ 100</span>
      </div>
      {report.tips.length === 0 ? (
        <p className="text-sm text-emerald-700">Looks great. Preview it, then save.</p>
      ) : (
        <ul className="space-y-2 text-sm">
          {shown.map(({ tip: t, targets }, i) => (
            <li key={i} className="flex gap-2">
              <Badge tone={t.level === "fix" ? "red" : "amber"}>{t.level === "fix" ? "fix" : "tip"}</Badge>
              {targets.length ? (
                <button type="button" className="text-left text-slate-700 hover:text-indigo-700" onClick={() => focusTarget(targets[0])}>
                  {t.message}
                  {targets.length > 1 && <span className="text-slate-500"> · {targets.length} bullets</span>}
                </button>
              ) : (
                <span className="text-slate-700">{t.message}</span>
              )}
            </li>
          ))}
        </ul>
      )}
      {groups.length > 5 && (
        <button type="button" className="mt-2 text-sm font-medium text-indigo-700 hover:underline" onClick={() => setAll(!all)}>
          {all ? "Show fewer" : `Show all ${groups.length}`}
        </button>
      )}
      {report.tips.length > 0 && (
        <div className="mt-3 border-t border-slate-100 pt-3">
          <Button className="w-full" variant="primary" busy={fix.isPending} onClick={() => fix.mutate()}>
            <Wand2 className="size-4" aria-hidden /> Fix all I can
          </Button>
          <p className="mt-1 text-xs text-slate-500">
            {ai ? "Rewrites flagged bullets and the summary, builds your Skills section. You review before anything changes." : "Builds your Skills section from your resume. Connect AI to fix bullets and the summary too."}
          </p>
          <ErrorText error={fix.error} />
        </div>
      )}
      {fix.data && (
        <FixReview
          result={fix.data}
          onApply={(chosen) => {
            onApply(applyChanges(doc, chosen));
            fix.reset();
          }}
          onCancel={() => fix.reset()}
        />
      )}
    </Card>
  );
}

function FixReview({ result, onApply, onCancel }: { result: FixResult; onApply: (chosen: FixChange[]) => void; onCancel: () => void }) {
  const [kept, setKept] = useState<boolean[]>(() => result.changes.map(() => true));
  const chosen = result.changes.filter((_, i) => kept[i]);
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-slate-950/60 p-0 sm:items-center sm:p-4" role="dialog" aria-label="Review fixes">
      <div className="flex max-h-[92dvh] w-full max-w-2xl flex-col overflow-hidden rounded-t-2xl bg-white sm:rounded-2xl">
        <div className="border-b border-slate-100 px-5 py-4">
          <p className="text-lg font-semibold text-slate-900">
            {result.changes.length ? `${result.changes.length} fix${result.changes.length === 1 ? "" : "es"} ready` : "Nothing to fix automatically"}
          </p>
          <p className="text-sm text-slate-600">
            Score {result.score_before} → <b className="text-emerald-700">{result.score_after}</b> with every fix. Untick any you don't want; nothing changes until you apply.
          </p>
        </div>
        <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-5 py-4 text-sm">
          {result.note && <Alert tone="info">{result.note}</Alert>}
          {result.changes.length > 1 && (
            <button type="button" className="text-xs font-medium text-indigo-700 hover:underline" onClick={() => setKept(kept.map(() => !kept.every(Boolean)))}>
              {kept.every(Boolean) ? "Untick all" : "Tick all"}
            </button>
          )}
          {result.changes.map((c, i) => (
            <label key={i} className={cx("flex cursor-pointer gap-3 rounded-xl border p-3", kept[i] ? "border-indigo-200 bg-indigo-50/30" : "border-slate-200 opacity-70")}>
              <input
                type="checkbox"
                className="mt-0.5 size-5 shrink-0 accent-indigo-600"
                checked={kept[i]}
                onChange={(e) => setKept(kept.map((k, j) => (j === i ? e.target.checked : k)))}
              />
              <span className="min-w-0">
                <span className="mb-1 block text-xs font-semibold uppercase tracking-wide text-slate-500">
                  {CHANGE_LABEL[c.op] ?? c.section}
                  {c.op === "remove" ? ` · ${c.section.replace(/^remove from /, "")}` : ""}
                </span>
                {c.before && <span className="block text-slate-500 line-through decoration-slate-300">{c.before}</span>}
                {c.after && <span className="mt-1 block text-slate-900">{c.after}</span>}
              </span>
            </label>
          ))}
          {result.remaining.length > 0 && (
            <div>
              <p className="mb-1 font-medium text-slate-900">Still needs you</p>
              <p className="mb-2 text-xs text-slate-500">These need facts only you know (a number, a link, a date), so HireFinch won't guess them.</p>
              <ul className="space-y-1">
                {result.remaining.map((t, i) => (
                  <li key={i} className="flex gap-2">
                    <Badge tone={t.level === "fix" ? "red" : "amber"}>{t.level === "fix" ? "fix" : "tip"}</Badge>
                    <span className="text-slate-700">{t.message}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
        <div className="flex justify-end gap-2 border-t border-slate-100 px-5 py-3 pb-[max(0.75rem,env(safe-area-inset-bottom))]">
          <Button onClick={onCancel}>Cancel</Button>
          <Button variant="primary" disabled={!chosen.length} onClick={() => onApply(chosen)}>
            Apply {chosen.length || ""} fix{chosen.length === 1 ? "" : "es"}
          </Button>
        </div>
      </div>
    </div>
  );
}

function focusTarget(id: string) {
  const el = document.getElementById(`rb-${id}`);
  el?.scrollIntoView({ behavior: "smooth", block: "center" });
  (el?.querySelector("textarea, input") as HTMLElement | null)?.focus();
}

/** One plain answer to "is my resume ready?", built from the two checks, which measure different things. */
function Verdict({ ats, report }: { ats: AtsResult | null; report: { score: number; tips: Tip[] } | null }) {
  if (!ats || !report) return null;
  const readable = ats.readability.score >= 95;
  const kw = ats.keywords;
  const kwFound = kw ? kw.required_found.length : 0;
  const kwTotal = kw ? kw.required_found.length + kw.required_missing.length : 0;
  const fixes = groupTips(report.tips.filter((t) => t.level === "fix")).length;
  const improvements = groupTips(report.tips.filter((t) => t.level === "improve")).length;
  const [title, tone] = !readable
    ? (["Fix before sending", "border-red-200 bg-red-50"] as const)
    : fixes || report.score < 85
      ? (["Readable, but could be stronger", "border-amber-200 bg-amber-50"] as const)
      : (["Ready to send", "border-emerald-200 bg-emerald-50"] as const);
  const Row = ({ ok, children }: { ok: boolean; children: React.ReactNode }) => (
    <li className="flex gap-2">
      <span className={cx("mt-0.5 grid size-4 shrink-0 place-items-center rounded-full text-[0.625rem] font-bold text-white", ok ? "bg-emerald-600" : "bg-amber-500")}>{ok ? "✓" : "!"}</span>
      <span>{children}</span>
    </li>
  );
  return (
    <div className={cx("rounded-2xl border p-4", tone)}>
      <p className="font-semibold text-slate-900">{title}</p>
      <ul className="mt-2 space-y-1.5 text-sm text-slate-700">
        <Row ok={readable}>{readable ? "An ATS can read every fact in it." : `An ATS misreads parts of it (${ats.readability.score}% read correctly). Fix this first.`}</Row>
        {kw ? (
          <Row ok={kwFound === kwTotal}>
            Job keywords: {kwFound} of {kwTotal} required skills found.
          </Row>
        ) : (
          <li className="pl-6 text-xs text-slate-500">Pick a job below to check its keywords.</li>
        )}
        <Row ok={!fixes && report.score >= 85}>
          For recruiters: {fixes + improvements ? `${fixes + improvements} thing${fixes + improvements === 1 ? "" : "s"} to improve (${report.score}/100).` : "reads well."}{" "}
          <span className="text-slate-500">This affects how people judge it, not whether an ATS can read it.</span>
        </Row>
      </ul>
    </div>
  );
}

interface AtsResult {
  readability: {
    score: number;
    pages: number;
    files: Record<string, { read: number; total: number; misses: { fact: string; detail: string }[] }>;
    checks: { check: string; ok: boolean; detail: string; severity: string }[];
  };
  keywords?: { required_found: string[]; required_missing: string[]; preferred_found: string[]; preferred_missing: string[] };
}

// The ATS parse test: renders the real PDF and Word files, reads them back like an applicant tracking
// system and compares every fact. With a job picked, also which of its skills a keyword search finds.
function AtsCard({ doc, onChange, onResult }: { doc: Doc; onChange: (d: Doc) => void; onResult: (r: AtsResult) => void }) {
  const [jobId, setJobId] = useState("");
  const [result, setResult] = useState<AtsResult | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [running, setRunning] = useState(false);
  const [testedAt, setTestedAt] = useState<Date | null>(null);
  const [again, setAgain] = useState(0);
  const immediate = useRef(false); // "Test again" runs at once; edits wait for a pause in typing
  const jobs = useQuery({
    queryKey: ["ats-jobs"],
    queryFn: () => api<{ items: { id: number; title: string; company: string }[] }>("/jobs?sort=score&page_size=40"),
    staleTime: 300_000,
  });
  useEffect(() => {
    const delay = immediate.current ? 0 : 2500;
    immediate.current = false;
    const t = setTimeout(() => {
      setRunning(true);
      api<AtsResult>("/resume-builder/ats-test", { body: { document: doc, job_id: jobId ? Number(jobId) : null } })
        .then((r) => {
          setResult(r);
          onResult(r);
          setError(null);
          setTestedAt(new Date());
        }, setError)
        .finally(() => setRunning(false));
    }, delay);
    return () => clearTimeout(t);
  }, [doc, jobId, again]);
  const addSkill = (skill: string) => {
    const skills = doc.skills.length ? [...doc.skills] : [{ name: "Skills", items: [] }];
    const last = skills.length - 1;
    skills[last] = { ...skills[last], items: [...skills[last].items, skill] };
    onChange({ ...doc, skills });
  };
  const r = result?.readability;
  const tone = !r ? "" : r.score >= 95 ? "text-emerald-700" : r.score >= 80 ? "text-amber-700" : "text-red-700";
  const failed = r?.checks.filter((c) => !c.ok) ?? [];
  const misses = r ? Object.entries(r.files).flatMap(([file, f]) => f.misses.map((m) => ({ ...m, file }))) : [];
  return (
    <Card title="ATS read test">
      <p className="-mt-1 mb-2 text-xs text-slate-500">
        There's no standard "ATS score": systems like Workday or Greenhouse read your file into fields, then recruiters search them. This test does
        exactly that: it creates your real PDF and Word files, reads them back and checks every fact.
      </p>
      {!r ? (
        <p className="text-sm text-slate-500">{running ? "Testing…" : "The test runs as you edit."}</p>
      ) : (
        <>
          <div className="flex items-baseline gap-2">
            <span className={cx("text-3xl font-semibold tabular-nums", tone)}>{r.score}%</span>
            <span className="text-sm text-slate-500">read correctly{running ? " · re-testing…" : ""}</span>
          </div>
          <ul className="mt-1 space-y-0.5 text-xs text-slate-600">
            {Object.entries(r.files).map(([file, f]) => (
              <li key={file}>
                {file}: {f.read} of {f.total} facts read back
              </li>
            ))}
            <li>
              File checks: {r.checks.length - failed.length} of {r.checks.length} passed · {r.pages} page{r.pages === 1 ? "" : "s"}
            </li>
          </ul>
          <div className="mt-2 flex items-center gap-2 text-xs text-slate-500">
            <span>{testedAt ? `Tested ${testedAt.toLocaleTimeString()} · re-tests as you edit` : ""}</span>
            <Button variant="ghost" className="ml-auto py-1 text-xs" disabled={running} onClick={() => {
                immediate.current = true;
                setAgain((n) => n + 1);
              }}>
              <RefreshCw className={cx("size-3.5", running && "animate-spin")} aria-hidden /> Test again
            </Button>
          </div>
          {(failed.length > 0 || misses.length > 0) && (
            <ul className="mt-2 space-y-1 text-sm">
              {failed.map((c) => (
                <li key={c.check} className="flex gap-2">
                  <Badge tone="red">file</Badge>
                  <span className="text-slate-700">{c.detail || c.check}</span>
                </li>
              ))}
              {misses.slice(0, 6).map((m, i) => (
                <li key={i} className="flex gap-2">
                  <Badge tone="amber">{m.file}</Badge>
                  <span className="text-slate-700">
                    {m.fact}: {m.detail}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
      <ErrorText error={error} />
      <div className="mt-3 border-t border-slate-100 pt-3">
        <Field label="Keyword match for a job (optional)">
          <select
            value={jobId}
            onChange={(e) => setJobId(e.target.value)}
            className="w-full rounded-lg border border-slate-200 bg-white px-2.5 py-2 text-sm focus:border-indigo-400 focus:outline-none"
          >
            <option value="">Pick one of your jobs…</option>
            {jobs.data?.items.map((j) => (
              <option key={j.id} value={j.id}>
                {j.title} · {j.company}
              </option>
            ))}
          </select>
        </Field>
        {result?.keywords && (
          <div className="mt-2 space-y-2 text-sm">
            <KeywordRow label="Required" found={result.keywords.required_found} missing={result.keywords.required_missing} onAdd={addSkill} />
            <KeywordRow label="Nice to have" found={result.keywords.preferred_found} missing={result.keywords.preferred_missing} onAdd={addSkill} />
            <p className="text-xs text-slate-500">A recruiter searching for a missing skill won't find you. Add it only if you really have it.</p>
          </div>
        )}
      </div>
    </Card>
  );
}

function KeywordRow({ label, found, missing, onAdd }: { label: string; found: string[]; missing: string[]; onAdd: (s: string) => void }) {
  if (!found.length && !missing.length) return null;
  return (
    <div>
      <p className="text-xs font-medium text-slate-600">
        {label}: {found.length} of {found.length + missing.length} found
      </p>
      <div className="mt-1 flex flex-wrap gap-1">
        {found.map((s) => (
          <Badge key={s} tone="green">
            {s}
          </Badge>
        ))}
        {missing.map((s) => (
          <button
            key={s}
            type="button"
            onClick={() => window.confirm(`Add ${s} to your Skills section? Only if you really have it.`) && onAdd(s)}
            className="inline-flex items-center gap-1 rounded-full border border-dashed border-red-300 px-2 py-0.5 text-xs text-red-700 hover:bg-red-50"
            title="Missing: tap to add it to your Skills section if you have it"
          >
            <Plus className="size-3" aria-hidden /> {s}
          </button>
        ))}
      </div>
    </div>
  );
}

function SummaryEditor({ doc, ai, onChange }: { doc: Doc; ai: boolean; onChange: (s: string) => void }) {
  const write = useAction(() => api<{ summary: string }>("/resume-builder/summary", { body: doc }), (r) => onChange(r.summary));
  const words = doc.summary.trim() ? doc.summary.trim().split(/\s+/).length : 0;
  return (
    <>
      <Field label="Summary" hint={`${words} words · aim for 40–80: your role, years of experience, strongest skills and a result`}>
        <TextArea rows={4} value={doc.summary} onChange={(e) => onChange(e.target.value)} />
      </Field>
      <Button className="mt-2" disabled={!ai} busy={write.isPending} onClick={() => write.mutate()} title={ai ? undefined : "Connect AI in Integrations"}>
        <Sparkles className="size-4" aria-hidden /> Write it from my experience
      </Button>
      <ErrorText error={write.error} />
    </>
  );
}

function EntryTools({ onRemove, onMove }: { onRemove: () => void; onMove: (d: -1 | 1) => void }) {
  return (
    <div className="flex gap-1">
      <Button variant="ghost" aria-label="Move up" onClick={() => onMove(-1)}>
        <ArrowUp className="size-4" />
      </Button>
      <Button variant="ghost" aria-label="Move down" onClick={() => onMove(1)}>
        <ArrowDown className="size-4" />
      </Button>
      <Button variant="ghost" aria-label="Remove" className="text-red-600" onClick={onRemove}>
        <Trash2 className="size-4" />
      </Button>
    </div>
  );
}

function ExperienceEditor({ entry, ai, onChange, onRemove, onMove }: { entry: Entry; ai: boolean; onChange: (e: Entry) => void; onRemove: () => void; onMove: (d: -1 | 1) => void }) {
  const set = (p: Partial<Entry>) => onChange({ ...entry, ...p });
  // Picking a month replaces any date text read from an uploaded file; the server writes it out again.
  const setDates = (p: Partial<Entry>) => set({ ...p, date_text: "" });
  return (
    <div id={`rb-${entry.id}`} className="rounded-xl border border-slate-200 p-3 sm:p-4">
      <div className="mb-2 flex items-start justify-between gap-2">
        <p className="pt-1.5 text-sm font-semibold text-slate-800">{entry.title || "New job"}{entry.company ? ` · ${entry.company}` : ""}</p>
        <EntryTools onRemove={onRemove} onMove={onMove} />
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Job title">
          <TextInput value={entry.title} onChange={(e) => set({ title: e.target.value })} />
        </Field>
        <Field label="Company">
          <TextInput value={entry.company} onChange={(e) => set({ company: e.target.value })} />
        </Field>
        <Field label="Start" hint={entry.date_text && !entry.start ? `Now shows “${entry.date_text}”` : undefined}>
          <TextInput type="month" value={toMonth(entry.start)} onChange={(e) => setDates({ start: fromMonth(e.target.value) })} />
        </Field>
        <Field label="End">
          <TextInput type="month" disabled={entry.is_current} value={toMonth(entry.end)} onChange={(e) => setDates({ end: fromMonth(e.target.value) })} />
        </Field>
      </div>
      <Checkbox label="I work here now" checked={entry.is_current} onChange={(v) => setDates({ is_current: v, end: v ? null : entry.end })} />
      <BulletsEditor bullets={entry.bullets} role={`${entry.title} at ${entry.company}`} ai={ai} onChange={(bullets) => set({ bullets })} />
    </div>
  );
}

function ProjectEditor({ project, ai, onChange, onRemove, onMove }: { project: Project; ai: boolean; onChange: (p: Project) => void; onRemove: () => void; onMove: (d: -1 | 1) => void }) {
  const set = (p: Partial<Project>) => onChange({ ...project, ...p });
  return (
    <div id={`rb-${project.id}`} className="rounded-xl border border-slate-200 p-3 sm:p-4">
      <div className="mb-2 flex items-start justify-between gap-2">
        <p className="pt-1.5 text-sm font-semibold text-slate-800">{project.name || "New project"}</p>
        <EntryTools onRemove={onRemove} onMove={onMove} />
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Project name">
          <TextInput value={project.name} onChange={(e) => set({ name: e.target.value })} />
        </Field>
        <Field label="Technologies" hint="Comma separated">
          <ListInput rows={1} value={project.technologies} onChange={(technologies) => set({ technologies })} />
        </Field>
      </div>
      <BulletsEditor bullets={project.bullets} role={`project ${project.name}`} ai={ai} onChange={(bullets) => set({ bullets })} />
    </div>
  );
}

function BulletsEditor({ bullets, role, ai, onChange }: { bullets: Bullet[]; role: string; ai: boolean; onChange: (b: Bullet[]) => void }) {
  return (
    <div className="mt-3">
      <p className="mb-1.5 text-sm font-medium text-slate-700">What you achieved</p>
      <p className="mb-2 text-xs text-slate-500">Formula: what you did + how much it helped (a real number) + how you did it. e.g. “Reduced page load time 40% by lazy-loading images”.</p>
      <ul className="space-y-2">
        {bullets.map((b) => (
          <BulletRow
            key={b.id}
            bullet={b}
            role={role}
            ai={ai}
            onChange={(text) => onChange(bullets.map((x) => (x.id === b.id ? { ...x, text } : x)))}
            onRemove={() => onChange(bullets.filter((x) => x.id !== b.id))}
          />
        ))}
      </ul>
      <Button variant="ghost" className="mt-1" onClick={() => onChange([...bullets, { id: uid(), text: "" }])}>
        <Plus className="size-4" aria-hidden /> Add a bullet
      </Button>
    </div>
  );
}

function BulletRow({ bullet, role, ai, onChange, onRemove }: { bullet: Bullet; role: string; ai: boolean; onChange: (t: string) => void; onRemove: () => void }) {
  const [facts, setFacts] = useState("");
  const [result, setResult] = useState<Suggestion | null>(null);
  const improve = useAction((withFacts: string) => api<Suggestion>("/resume-builder/improve-bullet", { body: { text: bullet.text, role, facts: withFacts } }), setResult);
  const asked = useRef<HTMLInputElement>(null);
  const short = bullet.text.trim().length < 8;
  const hint = useMemo(() => (ai ? (short ? "Write a few words first" : undefined) : "Connect AI in Integrations"), [ai, short]);
  useEffect(() => {
    if (result?.question) asked.current?.focus();
  }, [result]);
  return (
    <li id={`rb-${bullet.id}`} className="rounded-lg bg-slate-50/70 p-2 ring-1 ring-slate-200/70">
      <div className="flex gap-2">
        <TextArea rows={Math.min(6, Math.max(2, Math.ceil(bullet.text.length / 55)))} aria-label="Bullet" value={bullet.text} placeholder="e.g. Built the login API for the customer app" onChange={(e) => onChange(e.target.value)} />
        <Button variant="ghost" aria-label="Remove bullet" className="self-start text-slate-400 hover:text-red-600" onClick={onRemove}>
          <Trash2 className="size-4" />
        </Button>
      </div>
      <div className="mt-1.5 flex flex-wrap gap-2">
        <Button variant="ghost" className="text-indigo-700" disabled={!ai || short} title={hint} busy={improve.isPending && !improve.variables} onClick={() => improve.mutate("")}>
          <Wand2 className="size-4" aria-hidden /> Improve
        </Button>
      </div>
      {result && (
        <div className="mt-2 space-y-2 rounded-lg bg-white p-2.5 text-sm ring-1 ring-indigo-100">
          {result.text && (
            <>
              <p className="text-slate-800">{result.text}</p>
              <div className="flex gap-2">
                <Button
                  variant="primary"
                  onClick={() => {
                    onChange(result.text);
                    setResult(null);
                    setFacts("");
                  }}
                >
                  Use this
                </Button>
                <Button variant="ghost" onClick={() => setResult(null)}>
                  Keep mine
                </Button>
              </div>
            </>
          )}
          {result.rejected && <p className="text-xs text-amber-700">{result.rejected} HireFinch never adds facts you didn't write.</p>}
          {result.question && (
            <form
              className="space-y-1.5"
              onSubmit={(e) => {
                e.preventDefault();
                if (facts.trim()) improve.mutate(facts);
              }}
            >
              <label className="block text-xs font-medium text-slate-700">
                Make it measurable: {result.question}
                <input
                  ref={asked}
                  value={facts}
                  maxLength={300}
                  onChange={(e) => setFacts(e.target.value)}
                  placeholder="Your real answer, e.g. about 2,000 users"
                  className="mt-1 block w-full rounded-lg border border-slate-200 px-2.5 py-1.5 text-sm font-normal focus:border-indigo-400 focus:outline-none focus:ring-2 focus:ring-indigo-100"
                />
              </label>
              <Button type="submit" disabled={!facts.trim()} busy={improve.isPending && !!improve.variables}>
                Rewrite with my answer
              </Button>
              <p className="text-xs text-slate-500">Only use numbers you could explain in an interview. If you don't know, skip it.</p>
            </form>
          )}
          <ErrorText error={improve.error} />
        </div>
      )}
      {!result && <ErrorText error={improve.error} />}
    </li>
  );
}

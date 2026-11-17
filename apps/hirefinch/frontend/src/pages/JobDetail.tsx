import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, ExternalLink } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { api } from "../api/client";
import { InterviewPrep } from "../components/InterviewPrep";
import { JobSkillGaps, SkillAnswer, useJobSkillGaps } from "../components/SkillGaps";
import type { Contact, Criterion, JobDetail } from "../api/types";
import {
  Alert,
  Badge,
  Button,
  Card,
  ErrorText,
  Field,
  List,
  Loading,
  Modal,
  PageHeader,
  BAND_LABELS,
  ScoreBadge,
  Select,
  StatusBadge,
  TextInput,
  formatDate,
  outcomeTone,
  useAction,
  cx,
  sourceLabel,
} from "../components/ui";

const BAND_TEXT = BAND_LABELS;
const SKILL_GAP = /^(Required skill not evidenced in your resume|Preferred skill not evidenced):/;
const REQUIREMENT_LABELS: Record<string, string> = {
  required_skill: "Required skills",
  preferred_skill: "Nice to have",
  experience: "Experience",
  education: "Education",
  restriction: "Restrictions",
  location: "Location",
  certification: "Certifications",
};
const OUTCOME_TEXT: Record<string, string> = { pending: "Not sent yet", confirmed: "Confirmed received", uncertain: "Sent, not yet confirmed", failed: "Failed" };
const MODE_TEXT: Record<string, string> = { supervised: "you approve it", automatic: "applies automatically", manual: "you apply yourself" };

const ORDER = ["technical", "experience", "role", "domain", "location", "compensation"];

export function JobDetailPage() {
  const { id } = useParams();
  const query = useQuery({ queryKey: ["job", id], queryFn: () => api<JobDetail>(`/jobs/${id}`) });
  const [message, setMessage] = useState<string | null>(null);
  const post = (path: string, body?: unknown) => api<Record<string, unknown>>(`/jobs/${id}${path}`, { method: "POST", body });
  const evaluate = useAction(() => post("/evaluate"), () => setMessage("Match re-evaluated."));
  const shortlist = useAction(() => post("/shortlist"), () => setMessage("Shortlisted."));
  const tailor = useAction(() => post("/tailor"), () => setMessage("Tailored resume generated. Review it in Resume Studio."));
  const prepare = useAction(() => post("/application"), () => setMessage("Application prepared. See the Application Queue."));
  const status = useAction((body: { status: string; note?: string }) => post("/status", body), () => setMessage("Status updated."));
  const [adding, setAdding] = useState(false);
  const navigate = useNavigate();
  // One button that does every step this job still needs, then opens the finished application.
  const applyFlow = useAction(async () => {
    let current = query.data!.status;
    if (current === "discovered") {
      await post("/evaluate");
      current = "match_evaluated";
    }
    if (!["resume_ready", "awaiting_approval", "needs_manual", "ready_to_apply"].includes(current)) {
      await post("/tailor");
    }
    if (current !== "ready_to_apply") await post("/application");
    return true;
  }, () => navigate(`/queue?job=${id}`));

  if (query.isLoading) return <Loading />;
  if (query.error) return <ErrorText error={query.error} />;
  const job = query.data!;
  const match = job.match;
  const actionError = evaluate.error || shortlist.error || tailor.error || prepare.error || status.error || applyFlow.error;

  return (
    <>
      <button
        type="button"
        onClick={() => (window.history.length > 1 ? navigate(-1) : navigate("/jobs"))}
        className="mb-3 inline-flex items-center gap-1 text-sm font-medium text-indigo-700 hover:underline"
      >
        <ArrowLeft className="size-4" aria-hidden /> Back
      </button>
      <PageHeader
        title={job.title}
        subtitle={
          <span className="flex flex-wrap items-center gap-2">
            <span>{job.company}</span>·<span>{job.location ?? "location not stated"}</span>
            {job.work_mode && <Badge>{job.work_mode}</Badge>}
            <StatusBadge status={job.status} />
            <ScoreBadge score={job.score} band={job.band} />
            <a href={job.url} target="_blank" rel="noopener noreferrer nofollow" className="inline-flex items-center gap-1 text-indigo-600 hover:underline">
              Original posting <ExternalLink className="size-3.5" aria-hidden />
            </a>
          </span>
        }
      />

      <ApplyBox job={job} busy={applyFlow.isPending} onApply={() => applyFlow.mutate()} />

      <details className="mb-4 rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm">
        <summary className="cursor-pointer font-medium text-slate-700">More options</summary>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <Button busy={evaluate.isPending} onClick={() => evaluate.mutate()}>
            Re-check match
          </Button>
          <Button busy={shortlist.isPending} onClick={() => shortlist.mutate()} disabled={!["discovered", "match_evaluated"].includes(job.status)}
            title={["discovered", "match_evaluated"].includes(job.status) ? undefined : "Already shortlisted or further along"}>
            Shortlist
          </Button>
          <Button busy={tailor.isPending} onClick={() => tailor.mutate()}>
            Generate resume only
          </Button>
          <StatusMenu current={job.status} onSet={(s, note) => status.mutate({ status: s, note })} busy={status.isPending} />
        </div>
      </details>
      {message && <div className="mb-3"><Alert tone="success">{message}</Alert></div>}
      <div className="mb-3"><ErrorText error={actionError} /></div>

      <div className="space-y-4">
        {(job.flags.prompt_injection || job.flags.suspicious) && (
          <Alert tone="error">
            {job.flags.prompt_injection && (
              <div>
                <strong>This posting contains text that tries to instruct an AI.</strong> It was treated as data only and is excluded from automatic actions.
                {job.injection_snippets.length > 0 && (
                  <ul className="mt-1 list-disc pl-5 text-xs">
                    {job.injection_snippets.map((s, i) => (
                      <li key={i}>
                        <code>{s}</code>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
            {job.flags.suspicious && (
              <div className="mt-1">
                <strong>Looks suspicious:</strong> {(job.flags.suspicious_reasons ?? []).join("; ")}
              </div>
            )}
          </Alert>
        )}
        {job.flags.duplicate && <Alert tone="warning">This looks like the same job as <Link className="underline" to={`/jobs/${job.duplicate_of_id}`}>another listing you already have</Link>. Apply through that one.</Alert>}
        {job.flags.repost && <Alert tone="warning">This looks like a repost of <Link className="underline" to={`/jobs/${job.duplicate_of_id}`}>an earlier listing</Link>.</Alert>}
        {job.flags.truncated_description && <Alert tone="info">The source only provides a snippet of the description, so matching confidence is lower. Open the posting, or paste its full text with Import job, for a full score.</Alert>}
        {job.flags.email_available && (
          <Alert tone="success">
            An email address is available for this job. If no tailored resume is made, the agent drafts an email with your base resume for your
            approval (see Recruiter Outreach).
          </Alert>
        )}

        <div className="grid gap-4 lg:grid-cols-3">
          <div className="space-y-4 lg:col-span-2">
            {match ? (
              <Card title={`Match ${Math.round(match.score)}/100 · ${BAND_TEXT[match.band] ?? match.band}${match.confidence === "low" ? " · based on limited detail" : ""}`}>
                <p className="mb-3 text-sm font-medium text-slate-800">{match.explanation.recommendation}</p>
                {match.disqualifiers.length > 0 && (
                  <div className="mb-3">
                    <Alert tone="error">
                      <strong>Disqualifiers</strong> (these override the score):
                      <List items={match.disqualifiers} />
                    </Alert>
                  </div>
                )}
                <div className="space-y-2">
                  {ORDER.map((key) => match.breakdown[key]).filter(Boolean).map((c: Criterion) => (
                    <div key={c.key}>
                      <div className="flex justify-between text-sm">
                        <span className="font-medium text-slate-700">
                          {c.label} <span className="text-xs font-normal text-slate-500">({c.weight}% of the score)</span>
                        </span>
                        <span className="tabular-nums text-slate-600">{c.score === null ? "not stated" : `${Math.round(c.score * 100)}%`}</span>
                      </div>
                      <div className="mt-1 h-2 rounded bg-slate-100">
                        {c.score !== null && <div className="h-2 rounded bg-indigo-500" style={{ width: `${c.score * 100}%` }} />}
                      </div>
                      <p className="mt-0.5 text-xs text-slate-500">{c.detail}</p>
                    </div>
                  ))}
                </div>
                <div className="mt-4 grid gap-4 md:grid-cols-2">
                  <div>
                    <h3 className="mb-1 text-sm font-semibold">Your matching skills</h3>
                    <div className="flex flex-wrap gap-1">
                      {match.explanation.strongest_skills.length === 0 && <span className="text-sm text-slate-500">None found</span>}
                      {match.explanation.strongest_skills.map((s) => (
                        <Badge key={s.skill} tone="green" title={s.evidence.length ? `On your resume: ${s.evidence.join(", ")}` : undefined}>
                          {s.skill}
                        </Badge>
                      ))}
                    </div>
                  </div>
                  <div>
                    <h3 className="mb-1 text-sm font-semibold">Missing or weak</h3>
                    <JobSkillGaps jobId={job.id} />
                    {/* Skill gaps are answered above; anything else (e.g. experience) is listed as before. */}
                    <List items={match.explanation.resume_gaps.filter((g) => !SKILL_GAP.test(g))} empty={match.explanation.resume_gaps.length ? "" : "No gaps found"} />
                  </div>
                </div>
                <details className="mt-4 border-t border-slate-100 pt-3 text-sm">
                  <summary className="cursor-pointer text-slate-600">More detail: projects, interview tips, what the score could not check</summary>
                  <div className="mt-3 grid gap-4 md:grid-cols-2">
                    <div>
                      <h3 className="mb-1 text-sm font-semibold">Relevant projects</h3>
                      <List items={match.explanation.relevant_projects.map((p) => `${p.project}: ${p.matching_skills.join(", ")}`)} />
                    </div>
                    <div>
                      <h3 className="mb-1 text-sm font-semibold">Emphasise in an interview</h3>
                      <List items={match.explanation.interview_emphasis} />
                    </div>
                    <div>
                      <h3 className="mb-1 text-sm font-semibold">What the score could not check</h3>
                      <List items={match.explanation.confidence_reasons} />
                    </div>
                  </div>
                  <p className="mt-3 text-xs text-slate-500">Based on {match.explanation.years_used} years of experience from your resume.</p>
                </details>
              </Card>
            ) : (
              <Card title="Match">
                <p className="text-sm text-slate-600">Not evaluated yet. Upload a master resume in Profile, then choose Evaluate match.</p>
              </Card>
            )}
            <InterviewPrep jobId={job.id} interviewing={job.status === "interview_scheduled"} />
            <Card title="Job description">
              <Description text={job.description} />
            </Card>
          </div>

          <div className="space-y-4">
            <Card title="What the job asks for">
              {job.requirements.length === 0 ? (
                <p className="text-sm text-slate-500">Nothing extracted.</p>
              ) : (
                <dl className="space-y-2 text-sm">
                  {groupRequirements(job.requirements).map(([kind, values]) => (
                    <div key={kind}>
                      <dt className="text-xs font-semibold uppercase text-slate-500">{REQUIREMENT_LABELS[kind] ?? kind.replaceAll("_", " ")}</dt>
                      <dd className="mt-0.5 flex flex-wrap gap-1">
                        {values.map((v) => (
                          <Badge key={v} tone={kind === "required_skill" ? "indigo" : kind === "restriction" ? "red" : "slate"}>
                            {v}
                          </Badge>
                        ))}
                      </dd>
                    </div>
                  ))}
                </dl>
              )}
              <dl className="mt-3 space-y-1 border-t border-slate-100 pt-3 text-sm">
                <Row label="Salary" value={job.salary_text} />
                <Row label="Employment" value={job.employment_type} />
                <Row label="Posted" value={formatDate(job.posted_at)} />
                <Row label="Deadline" value={formatDate(job.deadline)} />
                <Row label="Discovered" value={formatDate(job.discovered_at, true)} />
                <Row label="Found via" value={sourceLabel(job.source, job.flags.via)} />
                <Row label="How to apply" value={(job.apply_method === "email" ? "By email" : job.apply_method === "manual" ? "On the employer's site" : job.apply_method) + (job.apply_email ? ` (${job.apply_email})` : "")} />
                <Row label="Still open?" value={job.liveness === "expired" ? "Closed" : job.liveness === "active" ? "Yes" : "Not checked"} />
              </dl>
            </Card>
            <Card title="Tailored resumes">
              {job.resume_versions.length === 0 ? (
                <p className="text-sm text-slate-500">None yet.</p>
              ) : (
                <ul className="space-y-1 text-sm">
                  {job.resume_versions.map((v) => (
                    <li key={v.id} className="flex items-center justify-between gap-2">
                      <Link className="text-indigo-700 hover:underline" to={`/resumes/${v.id}`}>
                        Version {v.version_no}
                      </Link>
                      <Badge tone={v.valid ? "green" : "red"}>{v.valid ? "ready" : "needs fixing"}</Badge>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
            {job.application && (
              <Card title="Application">
                <div className="space-y-1 text-sm">
                  <div>
                    <Badge tone={outcomeTone(job.application.outcome)}>{OUTCOME_TEXT[job.application.outcome] ?? job.application.outcome}</Badge>
                  </div>
                  <div className="text-slate-600">
                    {job.application.route === "email" ? "By email" : "On the employer's site"} · {MODE_TEXT[job.application.mode] ?? job.application.mode}
                  </div>
                  {job.application.confirmation_ref && <div>Reference: {job.application.confirmation_ref}</div>}
                  <Link className="text-indigo-700 hover:underline" to={`/queue?job=${id}`}>
                    Open in Application Queue
                  </Link>
                </div>
              </Card>
            )}
            <Card title="Recruiter contacts" actions={<Button onClick={() => setAdding(true)}>Add contact</Button>}>
              <Contacts contacts={job.recruiters} />
            </Card>
            {job.questions.length > 0 && (
              <Card title="Application form questions">
                <List items={job.questions} />
              </Card>
            )}
          </div>
        </div>
      </div>
      {adding && <AddContact jobId={job.id} onClose={() => setAdding(false)} />}
    </>
  );
}

function groupRequirements(reqs: { kind: string; value: string }[]): [string, string[]][] {
  const map = new Map<string, string[]>();
  for (const r of reqs) map.set(r.kind, [...(map.get(r.kind) ?? []), r.value]);
  return [...map.entries()];
}

function Row({ label, value }: { label: string; value: string | null | undefined }) {
  return (
    <div className="flex justify-between gap-2">
      <dt className="text-slate-500">{label}</dt>
      <dd className="text-right text-slate-800">{value || "—"}</dd>
    </div>
  );
}

const PREPARED = ["awaiting_approval", "ready_to_apply", "needs_manual", "application_failed"];
const DONE = ["applied", "recruiter_contacted", "interview_scheduled", "application_in_progress"];

function ApplyBox({ job, busy, onApply }: { job: JobDetail; busy: boolean; onApply: () => void }) {
  // Before tailoring, a quick check on required skills the resume doesn't show: a skill you confirm
  // goes into the tailored resume's Skills section. Skippable; never a blocking pop-up.
  const gaps = useJobSkillGaps(job.id);
  const unanswered = (gaps.data ?? []).filter((g) => g.required && !g.declined);
  const [checking, setChecking] = useState(false);
  if (DONE.includes(job.status)) {
    return (
      <div className="mb-4 rounded-2xl border border-emerald-200 bg-emerald-50/70 p-4">
        <p className="font-semibold text-emerald-900">You applied{job.application?.submitted_at ? ` on ${formatDate(job.application.submitted_at)}` : ""} ✓</p>
        <Link to="/tracker" className="mt-1 inline-block text-sm text-emerald-800 underline">
          Follow it in the Application Tracker
        </Link>
      </div>
    );
  }
  if (["rejected", "withdrawn", "expired"].includes(job.status)) return null;
  const prepared = PREPARED.includes(job.status);
  return (
    <div className="mb-4 flex flex-col gap-3 rounded-2xl border border-indigo-200 bg-gradient-to-br from-indigo-50 to-white p-4 sm:flex-row sm:flex-wrap sm:items-center sm:justify-between">
      <div>
        <p className="font-semibold text-slate-900">{prepared ? "Your application is ready" : "Apply for this job"}</p>
        <p className="text-sm text-slate-600">
          {prepared
            ? "Your tailored resume and answers are prepared. Finish it in the Application Queue (with the Apply kit or the browser extension)."
            : "HireFinch tailors your resume for this job, prepares the answers, and takes you to the last step."}
        </p>
      </div>
      {prepared ? (
        <Link to={`/queue?job=${job.id}`} className="inline-flex shrink-0 items-center justify-center gap-1.5 rounded-lg bg-gradient-to-b from-indigo-500 to-indigo-600 px-4 py-2.5 text-sm font-medium text-white shadow-sm">
          Finish your application
        </Link>
      ) : (
        <Button variant="primary" busy={busy} onClick={() => (unanswered.length && !checking ? setChecking(true) : onApply())} className="shrink-0 px-4 py-2.5">
          {busy ? "Preparing…" : checking ? "Continue to apply" : "Apply for this job"}
        </Button>
      )}
      {checking && !prepared && (
        <div className="w-full rounded-xl border border-indigo-100 bg-white p-3 sm:order-last">
          <p className="text-sm font-medium text-slate-900">Quick check before tailoring</p>
          <p className="text-xs text-slate-500">
            This job asks for {unanswered.length === 1 ? "a skill" : "skills"} your resume doesn't show. Any you know will be added to your tailored resume's Skills section.
          </p>
          <ul className="divide-y divide-slate-100">
            {unanswered.map((g) => (
              <SkillAnswer key={g.skill} skill={g.skill} />
            ))}
          </ul>
          <p className="mt-1 text-xs text-slate-500">Not sure? Skip it: press Continue to apply.</p>
        </div>
      )}
    </div>
  );
}

function StatusMenu({ current, onSet, busy }: { current: string; onSet: (s: string, note?: string) => void; busy: boolean }) {
  const [value, setValue] = useState("");
  const options =
    current === "withdrawn"
      ? [["match_evaluated", "Restore (undo dismissal)"]]
      : [
          ["interview_scheduled", "Interview scheduled"],
          ["rejected", "Rejected"],
          ["withdrawn", "Withdraw / dismiss"],
          ["expired", "Mark expired"],
        ];
  return (
    <div className="flex items-center gap-1">
      <Select aria-label="Update status" value={value} onChange={(e) => setValue(e.target.value)} className="w-52">
        <option value="">Update status…</option>
        {options.map(([v, l]) => (
          <option key={v} value={v}>
            {l}
          </option>
        ))}
      </Select>
      <Button disabled={!value} busy={busy} onClick={() => value && onSet(value)}>
        Save
      </Button>
    </div>
  );
}

export function Contacts({ contacts }: { contacts: Contact[] }) {
  const draft = useAction((id: number) => api(`/outreach/contacts/${id}/draft`, { method: "POST" }));
  if (contacts.length === 0) return <p className="text-sm text-slate-500">No recruiter contact is publicly listed. The agent never guesses addresses.</p>;
  return (
    <div className="space-y-2">
      <ul className="space-y-2 text-sm">
        {contacts.map((c) => (
          <li key={c.id} className="rounded border border-slate-100 p-2">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-medium">{c.name ?? c.email}</span>
              <Badge tone={c.verified ? "green" : "red"}>{c.verified ? "verified" : "unverified"}</Badge>
              <Badge>{sourceLabel(c.source)}</Badge>
            </div>
            {c.name && <div className="break-all text-slate-600">{c.email}</div>}
            {c.title && <div className="text-xs text-slate-500">{c.title}</div>}
            {c.verification_note && <div className="text-xs text-slate-500">{c.verification_note}</div>}
            <Button className="mt-1" disabled={!c.verified} busy={draft.isPending && draft.variables === c.id} onClick={() => draft.mutate(c.id)}>
              Draft email
            </Button>
          </li>
        ))}
      </ul>
      {draft.isSuccess && <Alert tone="success">Draft created. Review it in Recruiter Outreach.</Alert>}
      <ErrorText error={draft.error} />
    </div>
  );
}

function AddContact({ jobId, onClose }: { jobId: number; onClose: () => void }) {
  const [form, setForm] = useState({ email: "", name: "", title: "", note: "" });
  const save = useAction(
    () => api(`/outreach/jobs/${jobId}/contacts`, { method: "POST", body: { ...form, name: form.name || null, title: form.title || null } }),
    onClose,
  );
  const bind = (key: keyof typeof form) => ({ value: form[key], onChange: (e: { target: { value: string } }) => setForm({ ...form, [key]: e.target.value }) });
  return (
    <Modal title="Add a recruiter contact" onClose={onClose}>
      <p className="mb-3 text-sm text-slate-600">Only add an address that is published for this role or that the recruiter gave you. Never guess one.</p>
      <form
        className="space-y-3"
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate();
        }}
      >
        <Field label="Email">
          <TextInput type="email" required {...bind("email")} />
        </Field>
        <Field label="Name">
          <TextInput {...bind("name")} />
        </Field>
        <Field label="Title">
          <TextInput {...bind("title")} />
        </Field>
        <Field label="Where did you find this address?">
          <TextInput required minLength={5} {...bind("note")} />
        </Field>
        <ErrorText error={save.error} />
        <div className="flex justify-end gap-2">
          <Button onClick={onClose}>Cancel</Button>
          <Button type="submit" variant="primary" busy={save.isPending}>
            Add contact
          </Button>
        </div>
      </form>
    </Modal>
  );
}

// The posting as readable text; long ones start folded so the page stays short on phones.
function Description({ text }: { text: string }) {
  const [full, setFull] = useState(false);
  const long = text.length > 1500;
  return (
    <div>
      <p className={cx("whitespace-pre-line break-words text-sm leading-relaxed text-slate-700", long && !full && "line-clamp-[12]")}>{text}</p>
      {long && (
        <button type="button" onClick={() => setFull(!full)} className="mt-2 text-sm font-medium text-indigo-700 hover:underline">
          {full ? "Show less" : "Show the full description"}
        </button>
      )}
    </div>
  );
}

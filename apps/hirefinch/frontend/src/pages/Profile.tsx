import { useQuery } from "@tanstack/react-query";
import { Upload } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router";
import { ApiError, api } from "../api/client";
import { useMe } from "../auth";
import type { CommonAnswers, EmailStyle, MasterResume, SelfIdentification, Preferences, Profile, ProfileResponse, ResumeCandidates, WorkMode } from "../api/types";
import {
  Alert,
  Badge,
  Button,
  Card,
  Collapsible,
  Empty,
  ErrorText,
  Field,
  ListInput,
  Loading,
  NumberInput,
  PageHeader,
  Pre,
  Select,
  TextArea,
  TextInput,
  formatDate,
  useAction,
} from "../components/ui";

// A checkbox row big enough to tap on a phone: the whole row toggles it.
function Tick({ label, checked, onChange }: { label: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="flex min-h-11 cursor-pointer items-center gap-3 rounded-lg px-1 text-sm text-slate-700 hover:bg-slate-50">
      <input type="checkbox" className="size-5 shrink-0 rounded border-slate-300 accent-indigo-600" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      <span>{label}</span>
    </label>
  );
}

// A section's save button, at the bottom where the eye ends up after filling it in.
function SaveRow({ label, busy, disabled, hint, error, saved, onSave }: { label: string; busy: boolean; disabled?: boolean; hint?: string; error: unknown; saved: string | false; onSave: () => void }) {
  return (
    <div className="mt-5 border-t border-slate-100 pt-4">
      <div className="flex flex-wrap items-center gap-3">
        <Button variant="primary" busy={busy} disabled={disabled} onClick={onSave}>
          {label}
        </Button>
        {disabled && hint && <span className="text-xs text-red-600">{hint}</span>}
      </div>
      <div className="mt-2">
        <ErrorText error={error} />
        {saved && <Alert tone="success">{saved}</Alert>}
      </div>
    </div>
  );
}

export function ProfilePage() {
  const profile = useQuery({ queryKey: ["profile"], queryFn: () => api<ProfileResponse>("/profile") });
  return (
    <>
      <PageHeader
        title="Profile & Preferences"
        subtitle="Your resume, details and answers in one place. Open a section to change it. If something isn't here, HireFinch asks you instead of guessing."
      />
      <div className="space-y-4">
        <Masters />
        {profile.isLoading ? (
          <Loading />
        ) : profile.error ? (
          <ErrorText error={profile.error} />
        ) : (
          <>
            {profile.data!.candidate ? (
              <Collapsible
                summary={`${profile.data!.candidate.name} · ${profile.data!.candidate.years_experience} years · ${profile.data!.candidate.skills.length} skills found`}
              >
              <Card title="What HireFinch read from your resume">
                <dl className="grid gap-2 text-sm md:grid-cols-4">
                  <div>
                    <dt className="text-slate-500">Name</dt>
                    <dd>{profile.data!.candidate.name}</dd>
                  </div>
                  <div>
                    <dt className="text-slate-500">Current role</dt>
                    <dd>
                      {profile.data!.candidate.current_title} at {profile.data!.candidate.current_company}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-slate-500">Verified experience</dt>
                    <dd>
                      {profile.data!.candidate.years_experience} years ({profile.data!.candidate.years_including_internships} including internships)
                    </dd>
                  </div>
                  <div>
                    <dt className="text-slate-500">Computer science degree</dt>
                    <dd>{profile.data!.candidate.has_cs_degree ? "yes" : "no"}</dd>
                  </div>
                </dl>
                <div className="mt-3 flex flex-wrap gap-1">
                  {profile.data!.candidate.skills.map((s) => (
                    <Badge key={s} tone="indigo">
                      {s}
                    </Badge>
                  ))}
                </div>
              </Card>
              </Collapsible>
            ) : (
              <Alert tone="warning">Upload your resume above to start matching and tailoring.</Alert>
            )}
            <ProfileForm initial={profile.data!.profile} />
            <PreferencesForm initial={profile.data!.preferences} />
          </>
        )}
      </div>
    </>
  );
}

function Masters() {
  // Importing from the server's own folders is a local-development helper for the superadmin only.
  const canFind = useMe().role === "superadmin";
  const masters = useQuery({ queryKey: ["masters"], queryFn: () => api<MasterResume[]>("/resumes/masters") });
  const [findOpen, setFindOpen] = useState(false);
  const candidates = useQuery({ queryKey: ["candidates"], queryFn: () => api<ResumeCandidates>("/resumes/candidates"), enabled: findOpen });
  const [viewing, setViewing] = useState<number | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const upload = useAction((file: File) => {
    const form = new FormData();
    form.append("file", file);
    return api<MasterResume>("/resumes/masters", { method: "POST", form });
  });
  const importPath = useAction((path: string) => api<MasterResume>("/resumes/masters/import", { method: "POST", body: { path } }));
  const activate = useAction((id: number) => api(`/resumes/masters/${id}/activate`, { method: "POST" }));
  const reread = useAction((id: number) => api(`/resumes/masters/${id}/reread`, { method: "POST" }));
  const remove = useAction((id: number) => api<{ result: "deleted" | "archived" }>(`/resumes/masters/${id}`, { method: "DELETE" }));
  const list = masters.data ?? [];
  const active = list.find((m) => m.is_active);
  const better = active && [...list].filter((m) => !m.is_active && m.skills_count > active.skills_count).sort((a, b) => b.skills_count - a.skills_count)[0];
  const weak = !!active && (active.skills_count < 5 || active.warnings.length > 0);

  return (
    <Collapsible defaultOpen summary={active ? `In use: ${active.filename} · ${active.skills_count} skills` : "No resume yet: upload one to start."}>
    <Card title="Your resume">
      <div className="mb-4 flex flex-wrap gap-2">
          <input
            ref={fileRef}
            type="file"
            accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            className="hidden"
            aria-label="Resume file"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) upload.mutate(file);
              e.target.value = "";
            }}
          />
          <Button variant="primary" busy={upload.isPending} onClick={() => fileRef.current?.click()}>
            <Upload className="size-4" aria-hidden /> Upload PDF or DOCX
          </Button>
          <Link to="/resume-builder" className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3.5 py-2 text-sm font-medium text-slate-700 shadow-xs hover:bg-slate-50">
            Build or improve it on the site
          </Link>
          {canFind && <Button onClick={() => setFindOpen(!findOpen)}>Import from server</Button>}
      </div>
      <ErrorText error={upload.error || importPath.error || activate.error || reread.error || remove.error} />
      {remove.data?.result === "archived" && (
        <div className="mb-3">
          <Alert tone="success">Removed from your list. It is kept in the background because tailored resumes were made from it.</Alert>
        </div>
      )}
      {weak && (
        <div className="mb-3">
          <Alert tone="warning">
            <strong>Matching will be weaker with the resume in use.</strong>{" "}
            {active!.skills_count < 5 ? `HireFinch found only ${active!.skills_count} skill${active!.skills_count === 1 ? "" : "s"} in it` : "HireFinch had trouble reading parts of it"}.{" "}
            {better ? (
              <>
                “{better.filename}” has {better.skills_count} skills: choose <b>Use this one</b> next to it, or open <b>Check what we read</b> to fix this one.
              </>
            ) : (
              <>
                Open <b>Check what we read</b> to add what's missing, or upload a version with a clear Skills section.
              </>
            )}
          </Alert>
        </div>
      )}
      {findOpen && (
        <div className="mb-4 rounded border border-slate-200 p-3">
          {candidates.isLoading ? (
            <Loading />
          ) : candidates.error ? (
            candidates.error instanceof ApiError && candidates.error.status === 403 ? (
              <Empty>Importing files from the server is not available here. Upload your resume instead.</Empty>
            ) : (
              <ErrorText error={candidates.error} />
            )
          ) : candidates.data!.search_paths.length === 0 ? (
            <p className="text-sm text-slate-600">
              No search folders configured. Set <code>HIREFINCH_RESUME_SEARCH_PATHS</code> (comma-separated) in <code>.env</code>, or upload a file.
            </p>
          ) : candidates.data!.files.length === 0 ? (
            <Empty>No PDF or DOCX files named like a resume in {candidates.data!.search_paths.join(", ")}.</Empty>
          ) : (
            <ul className="space-y-1 text-sm">
              {candidates.data!.files.map((f) => (
                <li key={f.path} className="flex flex-wrap items-center justify-between gap-2">
                  <span className="break-all">
                    {f.path} <span className="text-xs text-slate-500">({Math.round(f.size / 1024)} KB, modified {formatDate(f.modified)})</span>
                  </span>
                  <Button busy={importPath.isPending && importPath.variables === f.path} onClick={() => importPath.mutate(f.path)}>
                    Import
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
      {masters.isLoading ? (
        <Loading />
      ) : masters.error ? (
        <ErrorText error={masters.error} />
      ) : masters.data!.length === 0 ? (
        <Empty>No master resume uploaded yet.</Empty>
      ) : (
        <ul className="divide-y divide-slate-100 text-sm">
          {masters.data!.map((m) => (
            <li key={m.id} className="py-2">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium break-all">{m.filename}</span>
                <Badge>{m.format}</Badge>
                {m.is_active && <Badge tone="green">in use</Badge>}
                {m.corrected && <Badge tone="indigo">corrected</Badge>}
                <span className="text-xs text-slate-500">
                  {formatDate(m.uploaded_at, true)} · {m.experience_count} roles · {m.skills_count} skills
                </span>
                <div className="ml-auto flex gap-2">
                  {!m.is_active && (
                    <Button busy={activate.isPending && activate.variables === m.id} onClick={() => activate.mutate(m.id)}>
                      Use this one
                    </Button>
                  )}
                  <Button onClick={() => setViewing(viewing === m.id ? null : m.id)}>{viewing === m.id ? "Close" : "Check what we read"}</Button>
                  {!m.is_active && (
                    <Button
                      variant="ghost"
                      className="text-red-600"
                      busy={remove.isPending && remove.variables === m.id}
                      onClick={() => window.confirm(`Delete “${m.filename}”? This can't be undone.`) && remove.mutate(m.id)}
                    >
                      Delete
                    </Button>
                  )}
                </div>
              </div>
              {m.warnings.length > 0 && (
                <div className="mt-1">
                  <Alert tone="warning">
                    Parts we couldn't read clearly: {m.warnings.join("; ")}.{" "}
                    <button
                      type="button"
                      className="font-medium underline"
                      disabled={reread.isPending}
                      onClick={() => reread.mutate(m.id)}
                    >
                      {reread.isPending && reread.variables === m.id ? "Reading…" : "Read it again"}
                    </button>{" "}
                    (HireFinch's reader gets better over time).
                  </Alert>
                </div>
              )}
              {viewing === m.id && <MasterEditor id={m.id} />}
            </li>
          ))}
        </ul>
      )}
    </Card>
    </Collapsible>
  );
}

function MasterEditor({ id }: { id: number }) {
  const query = useQuery({ queryKey: ["master", id], queryFn: () => api<MasterResume>(`/resumes/masters/${id}`) });
  const [text, setText] = useState("");
  const [parseError, setParseError] = useState<string | null>(null);
  useEffect(() => {
    if (query.data?.document) setText(JSON.stringify(query.data.document, null, 2));
  }, [query.data]);
  const save = useAction((doc: unknown) => api(`/resumes/masters/${id}/document`, { method: "PUT", body: doc }));
  if (query.isLoading) return <Loading />;
  if (query.error) return <ErrorText error={query.error} />;
  return (
    <div className="mt-3 grid gap-3 lg:grid-cols-2">
      <div>
        <h3 className="mb-1 text-sm font-semibold">As parsed (plain text)</h3>
        <Pre>{query.data!.text}</Pre>
        <a className="mt-1 inline-block text-xs text-indigo-700 hover:underline" href={`/api/resumes/masters/${id}/file`}>
          Download original file (never modified)
        </a>
      </div>
      <div>
        <h3 className="mb-1 text-sm font-semibold">Correct the structure</h3>
        <p className="mb-1 text-xs text-slate-500">Fix anything the parser got wrong. Your corrected structure becomes the source of truth for tailoring; the original file is untouched.</p>
        <TextArea rows={24} className="font-mono text-xs" value={text} onChange={(e) => setText(e.target.value)} aria-label="Resume structure JSON" />
        {parseError && <Alert tone="error">{parseError}</Alert>}
        <ErrorText error={save.error} />
        {save.isSuccess && <Alert tone="success">Saved.</Alert>}
        <Button
          className="mt-2"
          variant="primary"
          busy={save.isPending}
          onClick={() => {
            try {
              const doc = JSON.parse(text);
              setParseError(null);
              save.mutate(doc);
            } catch (err) {
              setParseError(`Not valid JSON: ${(err as Error).message}`);
            }
          }}
        >
          Save corrections
        </Button>
      </div>
    </div>
  );
}

/** CTC is in lakhs per annum (1 LPA = ₹1,00,000); the same rule as the server (MAX_CTC_LPA). */
const MAX_CTC_LPA = 500;

export function ctcProblem(value: number | null): string | null {
  if (value === null) return null;
  if (value <= 0) return "Enter a CTC above 0, in lakhs per annum (LPA), e.g. 12.5.";
  if (value > MAX_CTC_LPA)
    return `${value.toLocaleString("en-IN")} looks like rupees. Enter lakhs per annum: ₹${value.toLocaleString("en-IN")} is ${(value / 100000).toLocaleString("en-IN", { maximumFractionDigits: 2 })} LPA.`;
  return null;
}

function lpaHint(value: number | null, normal: string) {
  const problem = ctcProblem(value);
  return problem ? <span className="font-medium text-red-600">{problem}</span> : normal;
}

const triState = (v: boolean | null) => (v === null ? "" : v ? "yes" : "no");
const fromTri = (v: string) => (v === "" ? null : v === "yes");

function ProfileForm({ initial }: { initial: Profile }) {
  const [p, setP] = useState<Profile>(initial);
  const [answersText, setAnswersText] = useState(Object.entries(initial.custom_answers).map(([k, v]) => `${k} = ${v}`).join("\n"));
  const save = useAction((override?: Profile) => {
    const base = override ?? p;
    const custom_answers = Object.fromEntries(
      answersText
        .split("\n")
        .map((line) => line.split("="))
        .filter((parts) => parts.length >= 2 && parts[0].trim())
        .map(([k, ...rest]) => [k.trim(), rest.join("=").trim()]),
    );
    const clean = Object.fromEntries(Object.entries(base).map(([k, v]) => [k, v === "" ? null : v]));
    return api<Profile>("/profile", { method: "PUT", body: { ...clean, custom_answers } });
  });
  const ctcInvalid = !!(ctcProblem(p.current_ctc_lpa) || ctcProblem(p.expected_ctc_lpa));
  const text = (key: keyof Profile, label: string, type = "text", hint?: string) => (
    <Field label={label} hint={hint}>
      <TextInput type={type} value={(p[key] as string | null) ?? ""} onChange={(e) => setP({ ...p, [key]: e.target.value })} />
    </Field>
  );
  // Each section saves the whole profile; the success note shows under the button that was used.
  const [savedIn, setSavedIn] = useState<string | null>(null);
  const saveFrom = (section: string) => {
    setSavedIn(section);
    save.mutate(undefined);
  };
  const row = (section: string) => (
    <SaveRow
      label="Save"
      busy={save.isPending && savedIn === section}
      disabled={ctcInvalid}
      hint="Fix the CTC in Contact and basics first."
      error={savedIn === section ? save.error : null}
      saved={savedIn === section && save.isSuccess && "Saved."}
      onSave={() => saveFrom(section)}
    />
  );
  const filled = (v: unknown) => v !== null && v !== "" && v !== undefined;
  const commonSet = Object.values(p.common_answers ?? EMPTY_COMMON).filter((v) => filled(v) && v !== false).length;
  const selfSet = Object.values(p.self_identification ?? EMPTY_SELF_ID).filter(filled).length;
  const style = p.email_style ?? DEFAULT_STYLE;
  return (
    <>
      <Collapsible defaultOpen={ctcInvalid} summary={[p.full_name, p.contact_email, p.phone].filter(Boolean).join(" · ") || "Name, email, phone, notice period, CTC."}>
        <Card title="Contact and basics">
          {ctcInvalid && (
            <div className="mb-4">
              <Alert tone="error">CTC must be in lakhs per annum (LPA), for example 12.49 rather than 1249000. Correct the highlighted CTC fields; saving (including adding skills) is blocked until then.</Alert>
            </div>
          )}
          <div className="grid gap-3 md:grid-cols-3">
            {text("full_name", "Full name")}
            {text("headline", "Headline")}
            {text("location", "Location")}
            {text("contact_email", "Contact email", "email", "Used in applications and as Reply-To")}
            {text("phone", "Phone", "tel", "Digits with optional +country code, e.g. +91 98765 43210")}
            {text("notification_email", "Notification email", "email", "Where HireFinch sends you updates")}
            {text("linkedin_url", "LinkedIn URL", "url", "e.g. https://www.linkedin.com/in/your-name")}
            {text("portfolio_url", "Portfolio URL", "url", "e.g. https://github.com/your-name")}
            <Field label="Notice period (days)">
              <NumberInput value={p.notice_period_days} min={0} onChange={(v) => setP({ ...p, notice_period_days: v })} />
            </Field>
            <Field label="Current CTC (LPA)" hint={lpaHint(p.current_ctc_lpa, "Sensitive. Only used when a form asks; never retained after submission.")}>
              <NumberInput value={p.current_ctc_lpa} min={0.1} max={500} step="0.01" aria-invalid={!!ctcProblem(p.current_ctc_lpa)} className={ctcProblem(p.current_ctc_lpa) ? "border-red-400 ring-4 ring-red-500/10" : undefined} onChange={(v) => setP({ ...p, current_ctc_lpa: v })} />
            </Field>
            <Field label="Expected CTC (LPA)" hint={lpaHint(p.expected_ctc_lpa, "If empty, salary questions pause for you.")}>
              <NumberInput value={p.expected_ctc_lpa} min={0.1} max={500} step="0.01" aria-invalid={!!ctcProblem(p.expected_ctc_lpa)} className={ctcProblem(p.expected_ctc_lpa) ? "border-red-400 ring-4 ring-red-500/10" : undefined} onChange={(v) => setP({ ...p, expected_ctc_lpa: v })} />
            </Field>
            <Field label="Authorised to work in" hint="Countries, comma-separated">
              <ListInput value={p.authorized_to_work_in} rows={1} onChange={(v) => setP({ ...p, authorized_to_work_in: v })} />
            </Field>
            <Field label="Requires visa sponsorship">
              <Select value={triState(p.requires_sponsorship)} onChange={(e) => setP({ ...p, requires_sponsorship: fromTri(e.target.value) })}>
                <option value="">Not set (ask me)</option>
                <option value="yes">Yes</option>
                <option value="no">No</option>
              </Select>
            </Field>
            <Field label="Willing to relocate">
              <Select value={triState(p.willing_to_relocate)} onChange={(e) => setP({ ...p, willing_to_relocate: fromTri(e.target.value) })}>
                <option value="">Not set (ask me)</option>
                <option value="yes">Yes</option>
                <option value="no">No</option>
              </Select>
            </Field>
            <div className="flex items-end">
              <Tick label="Count internships as experience" checked={p.count_internships_as_experience} onChange={(v) => setP({ ...p, count_internships_as_experience: v })} />
            </div>
          </div>
          {row("basics")}
        </Card>
      </Collapsible>

      <Collapsible summary={p.verified_extra_skills.length ? `${p.verified_extra_skills.length} added: ${p.verified_extra_skills.map((x) => x.name).slice(0, 4).join(", ")}${p.verified_extra_skills.length > 4 ? "…" : ""}` : "Skills you have that aren't on your resume, with proof."}>
        <Card title="Skills not on your resume">
          <SkillsEditor
            skills={p.verified_extra_skills}
            saving={save.isPending}
            blocked={ctcInvalid ? "Fix the CTC in Contact and basics first: the profile cannot be saved while it looks like rupees." : null}
            onChange={(verified_extra_skills) => {
              const next = { ...p, verified_extra_skills };
              setP(next);
              setSavedIn("skills");
              save.mutate(next); // saved at once, so an added skill is never lost or left half-filled
            }}
          />
          <div className="mt-2">
            <ErrorText error={savedIn === "skills" ? save.error : null} />
          </div>
        </Card>
      </Collapsible>

      <Collapsible summary={`Answers HireFinch uses on application forms · ${commonSet} of 8 set${answersText.trim() ? ", plus your own" : ""}.`}>
        <Card title="Application questions">
          <CommonQuestions value={p.common_answers ?? EMPTY_COMMON} onChange={(common_answers) => setP({ ...p, common_answers })} />
          <div className="mt-5">
            <Field label="Your answers to other recurring questions" hint="One per line: a keyword from the question = your answer (e.g. 'nationality = Indian', 'immediate joiner = No', 'shift = Yes'). Used whenever a form question contains the keyword, by HireFinch and the browser extension.">
              <TextArea rows={5} value={answersText} onChange={(e) => setAnswersText(e.target.value)} />
            </Field>
          </div>
          {row("questions")}
        </Card>
      </Collapsible>

      <Collapsible summary={selfSet ? `${selfSet} of 6 answered. Only used exactly as you wrote it.` : "Optional equal-opportunity answers. Empty means you answer them yourself."}>
        <Card title="Self-identification (optional)">
          <SelfId value={p.self_identification ?? EMPTY_SELF_ID} onChange={(self_identification) => setP({ ...p, self_identification })} />
          {row("self")}
        </Card>
      </Collapsible>

      <Collapsible summary={`How your recruiter emails sound: ${style.tone}, ${style.length}.`}>
        <Card title="Email style">
          <EmailStyleEditor value={style} onChange={(email_style) => setP({ ...p, email_style })} />
          {row("style")}
        </Card>
      </Collapsible>
    </>
  );
}

function SkillsEditor({ skills, onChange, saving, blocked }: { skills: Profile["verified_extra_skills"]; onChange: (s: Profile["verified_extra_skills"]) => void; saving: boolean; blocked: string | null }) {
  const [name, setName] = useState("");
  const [evidence, setEvidence] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const add = () => {
    if (blocked) return setProblem(blocked);
    const n = name.trim();
    const ev = evidence.trim();
    if (!n) return setProblem("Enter the skill name.");
    if (ev.length < 3) return setProblem("Add where it can be verified: a project, certificate or link (at least 3 characters).");
    if (skills.some((s) => s.name.toLowerCase() === n.toLowerCase())) return setProblem(`${n} is already in your list.`);
    setProblem(null);
    onChange([...skills, { name: n, evidence: ev }]);
    setName("");
    setEvidence("");
  };
  return (
    <div>
      <p className="mb-3 text-xs text-slate-500">Skills not on your resume, with where they can be verified. Only these may be added to a tailored resume. Adding or removing a skill saves straight away.</p>
      {skills.length === 0 ? (
        <p className="mb-3 rounded-lg border border-dashed border-slate-200 px-3 py-2.5 text-xs text-slate-500">No extra skills yet.</p>
      ) : (
        <ul className="mb-3 flex flex-wrap gap-2">
          {skills.map((s) => (
            <li key={s.name} className="group inline-flex max-w-full items-center gap-1.5 rounded-full border border-indigo-200 bg-indigo-50 py-1 pl-3 pr-1 text-sm text-indigo-800" title={`Evidence: ${s.evidence}`}>
              <span className="font-medium">{s.name}</span>
              <span className="max-w-[14rem] truncate text-xs text-indigo-500">· {s.evidence}</span>
              <button
                type="button"
                aria-label={`Remove ${s.name}`}
                disabled={saving}
                onClick={() => (blocked ? setProblem(blocked) : onChange(skills.filter((x) => x.name !== s.name)))}
                className="grid size-5 place-items-center rounded-full text-indigo-400 hover:bg-indigo-100 hover:text-indigo-700"
              >
                ✕
              </button>
            </li>
          ))}
        </ul>
      )}
      <div
        className="flex flex-col gap-2 sm:flex-row"
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            add();
          }
        }}
      >
        <TextInput aria-label="Skill" placeholder="Skill, e.g. Terraform" value={name} maxLength={80} onChange={(e) => setName(e.target.value)} className="sm:w-40" />
        <TextInput aria-label="Evidence" placeholder="Evidence: project, certificate or link" value={evidence} maxLength={500} onChange={(e) => setEvidence(e.target.value)} />
        <Button onClick={add} busy={saving} className="shrink-0">
          Add skill
        </Button>
      </div>
      {problem && <p role="alert" className="mt-1.5 text-xs text-red-600">{problem}</p>}
    </div>
  );
}

const EMPTY_SELF_ID: SelfIdentification = { gender: null, pronouns: null, ethnicity: null, disability: null, veteran: null, date_of_birth: null };
const EMPTY_COMMON: CommonAnswers = {
  country_of_residence: null,
  highest_education: null,
  managed_team: null,
  willing_onsite: null,
  background_check_consent: null,
  criminal_record: null,
  how_did_you_hear: null,
  accept_declarations: false,
};
const orNull = (v: string) => (v.trim() ? v : null);

function YesNo({ label, value, onChange, hint }: { label: string; value: boolean | null; onChange: (v: boolean | null) => void; hint?: string }) {
  return (
    <Field label={label} hint={hint}>
      <Select value={triState(value)} onChange={(e) => onChange(fromTri(e.target.value))}>
        <option value="">Not set (ask me on the form)</option>
        <option value="yes">Yes</option>
        <option value="no">No</option>
      </Select>
    </Field>
  );
}

function CommonQuestions({ value, onChange }: { value: CommonAnswers; onChange: (v: CommonAnswers) => void }) {
  const set = (patch: Partial<CommonAnswers>) => onChange({ ...value, ...patch });
  return (
    <div>
      <p className="mb-3 text-xs text-slate-500">
        Answer these once and the agent uses them on every form. It also answers from your resume: "Have you worked at {"{company}"} before?" from your employers, "Are you based in {"{city}"}?" from your
        location, education and total experience. Anything left empty is asked on the form.
      </p>
      <div className="grid gap-3 md:grid-cols-3">
        <Field label="Country of residence">
          <TextInput list="countries" maxLength={60} value={value.country_of_residence ?? ""} onChange={(e) => set({ country_of_residence: orNull(e.target.value) })} />
          <datalist id="countries">
            <option value="India" />
            <option value="United States" />
            <option value="United Kingdom" />
            <option value="Singapore" />
            <option value="United Arab Emirates" />
          </datalist>
        </Field>
        <Field label="Highest education" hint="Empty: the first line of Education on your resume">
          <TextInput maxLength={120} placeholder="e.g. Bachelor of Commerce" value={value.highest_education ?? ""} onChange={(e) => set({ highest_education: orNull(e.target.value) })} />
        </Field>
        <Field label="How did you hear about the job?" hint="Used for that question on every form">
          <TextInput list="sources" maxLength={80} value={value.how_did_you_hear ?? ""} onChange={(e) => set({ how_did_you_hear: orNull(e.target.value) })} />
          <datalist id="sources">
            <option value="Company website" />
            <option value="LinkedIn" />
            <option value="Job board" />
            <option value="Referral" />
          </datalist>
        </Field>
        <YesNo label="Have you managed a team?" value={value.managed_team} onChange={(v) => set({ managed_team: v })} />
        <YesNo label="Can you work on-site / from the office?" value={value.willing_onsite} onChange={(v) => set({ willing_onsite: v })} />
        <YesNo label="Consent to a background check?" value={value.background_check_consent} onChange={(v) => set({ background_check_consent: v })} />
        <YesNo label="Ever convicted of a criminal offence?" value={value.criminal_record} onChange={(v) => set({ criminal_record: v })} hint="Answered exactly as you set it" />
        <div className="flex items-end md:col-span-2">
          <Tick
            label="Accept standard declarations for me (“I certify the information is accurate”, privacy notice acknowledgements)"
            checked={value.accept_declarations}
            onChange={(v) => set({ accept_declarations: v })}
          />
        </div>
      </div>
    </div>
  );
}

function SelfId({ value, onChange }: { value: SelfIdentification; onChange: (v: SelfIdentification) => void }) {
  const set = (patch: Partial<SelfIdentification>) => onChange({ ...value, ...patch });
  const text = (key: keyof Omit<SelfIdentification, "date_of_birth">, label: string, options: string[]) => (
    <Field label={label}>
      <TextInput list={`sid-${key}`} maxLength={80} placeholder="Not set (ask me)" value={value[key] ?? ""} onChange={(e) => set({ [key]: orNull(e.target.value) })} />
      <datalist id={`sid-${key}`}>
        {[...options, "Prefer not to say"].map((o) => (
          <option key={o} value={o} />
        ))}
      </datalist>
    </Field>
  );
  return (
    <div>
      <p className="mb-3 text-xs text-slate-500">
        Many employers ask these equal-opportunity questions. The agent answers them <b>only</b> with what you write here, never guessed from your name or resume. Write “Prefer not to say” to
        decline everywhere, or leave a field empty to answer it yourself on each form.
      </p>
      <div className="grid gap-3 md:grid-cols-3">
        {text("gender", "Gender", ["Male", "Female", "Non-binary"])}
        {text("pronouns", "Pronouns", ["He/him", "She/her", "They/them"])}
        {text("ethnicity", "Ethnicity", ["Asian", "South Asian"])}
        {text("disability", "Disability", ["No", "Yes"])}
        {text("veteran", "Veteran status", ["I am not a protected veteran", "I am a protected veteran"])}
        <Field label="Date of birth" hint="Only some forms ask; empty = ask me">
          <TextInput type="date" value={value.date_of_birth ?? ""} onChange={(e) => set({ date_of_birth: e.target.value || null })} />
        </Field>
      </div>
    </div>
  );
}

const DEFAULT_STYLE: EmailStyle = { tone: "professional", length: "short", signature: null, template: null, subject_template: null, html: true };
const PLACEHOLDERS = ["greeting", "first_name", "job_title", "company", "job_url", "current_title", "current_company", "years", "skills", "projects", "qualifications", "attachment_note", "signature", "name"];

function EmailStyleEditor({ value, onChange }: { value: EmailStyle; onChange: (v: EmailStyle) => void }) {
  const set = (patch: Partial<EmailStyle>) => onChange({ ...value, ...patch });
  return (
    <div>
      <p className="mb-3 text-xs text-slate-500">
        How HireFinch writes recruiter emails for you. With an AI provider each email is written in this tone from your verified facts, and checked so it adds nothing new. Without one, your template is filled in.
      </p>
      <div className="grid gap-3 md:grid-cols-3">
        <Field label="Tone">
          <Select value={value.tone} onChange={(e) => set({ tone: e.target.value as EmailStyle["tone"] })}>
            <option value="professional">Professional</option>
            <option value="warm">Warm</option>
            <option value="concise">Concise</option>
            <option value="enthusiastic">Enthusiastic</option>
          </Select>
        </Field>
        <Field label="Length">
          <Select value={value.length} onChange={(e) => set({ length: e.target.value as EmailStyle["length"] })}>
            <option value="short">Short (about 120 words)</option>
            <option value="medium">Medium (about 190 words)</option>
          </Select>
        </Field>
        <div className="flex items-end">
          <Tick label="Send a formatted (HTML) version too" checked={value.html} onChange={(v) => set({ html: v })} />
        </div>
        <Field label="Signature" hint="Empty: “Best regards,” your name (bold), current role, then 📧 email, 📞 phone, 🔗 LinkedIn. Use **text** for bold.">
          <TextArea rows={3} maxLength={600} value={value.signature ?? ""} onChange={(e) => set({ signature: e.target.value || null })} />
        </Field>
        <Field label="Subject template" hint="Empty: “{job_title} at {company} — {name}”">
          <TextInput maxLength={200} value={value.subject_template ?? ""} onChange={(e) => set({ subject_template: e.target.value || null })} />
        </Field>
        <details className="md:col-span-3 text-sm">
          <summary className="cursor-pointer py-1 text-slate-600">Write your own email template (optional)</summary>
          <Field label="Body template" className="mt-2" hint={<>Leave empty to use the built-in email. Words in braces are filled in for each job: {PLACEHOLDERS.map((x) => `{${x}}`).join(" ")}</>}>
            <TextArea rows={6} maxLength={4000} className="font-mono text-xs" value={value.template ?? ""} onChange={(e) => set({ template: e.target.value || null })} />
          </Field>
        </details>
      </div>
    </div>
  );
}

const MODES: WorkMode[] = ["remote", "hybrid", "onsite"];
const MODE_LABELS: Record<WorkMode, string> = { remote: "Remote", hybrid: "Hybrid", onsite: "On-site" };

function PreferencesForm({ initial }: { initial: Preferences }) {
  const [p, setP] = useState<Preferences>(initial);
  const save = useAction(() => api<Preferences>("/preferences", { method: "PUT", body: p }));
  const list = (key: "target_roles" | "preferred_locations" | "target_companies" | "excluded_companies" | "excluded_keywords", label: string) => (
    <Field label={label}>
      <ListInput value={p[key]} onChange={(v) => setP({ ...p, [key]: v })} />
    </Field>
  );
  const target = p.target_compensation_lpa ?? [0, 0];
  const summary = [p.target_roles.slice(0, 3).join(", "), p.preferred_locations.slice(0, 3).join(", ")].filter(Boolean).join(" · ") || "Roles, places and pay you're looking for.";
  return (
    <Collapsible summary={summary}>
    <Card title="Job preferences">
      <div className="grid gap-3 md:grid-cols-3">
        {list("target_roles", "Target roles")}
        {list("preferred_locations", "Preferred locations")}
        <Field label="Work modes you accept">
          <div className="flex flex-wrap gap-x-4">
            {MODES.map((m) => (
              <Tick key={m} label={MODE_LABELS[m]} checked={p.work_modes.includes(m)} onChange={(v) => setP({ ...p, work_modes: v ? [...p.work_modes, m] : p.work_modes.filter((x) => x !== m) })} />
            ))}
          </div>
        </Field>
        <Field label="Minimum compensation (LPA)">
          <NumberInput value={p.min_compensation_lpa} min={0} onChange={(v) => setP({ ...p, min_compensation_lpa: v })} />
        </Field>
        <Field label="Target compensation">
          <div className="flex gap-2">
            <label className="flex-1 text-xs text-slate-500">
              From (LPA)
              <NumberInput aria-label="Target from (LPA)" value={target[0]} min={0} onChange={(v) => setP({ ...p, target_compensation_lpa: [v ?? 0, target[1]] })} />
            </label>
            <label className="flex-1 text-xs text-slate-500">
              To (LPA)
              <NumberInput aria-label="Target to (LPA)" value={target[1]} min={0} onChange={(v) => setP({ ...p, target_compensation_lpa: [target[0], v ?? 0] })} />
            </label>
          </div>
        </Field>
        <Field label="Exchange rates to INR" hint="e.g. USD=84, EUR=91. Without a rate, foreign salaries count as unknown.">
          <TextInput
            defaultValue={Object.entries(p.fx_rates_to_inr).map(([k, v]) => `${k}=${v}`).join(", ")}
            onBlur={(e) =>
              setP({
                ...p,
                fx_rates_to_inr: Object.fromEntries(
                  e.target.value
                    .split(",")
                    .map((x) => x.split("=").map((s) => s.trim()))
                    .filter(([k, v]) => k && v && !Number.isNaN(Number(v)))
                    .map(([k, v]) => [k.toUpperCase(), Number(v)]),
                ),
              })
            }
          />
        </Field>
        {list("target_companies", "Target companies")}
        {list("excluded_companies", "Excluded companies")}
        {list("excluded_keywords", "Excluded keywords")}
        <Field label="Allowed experience gap (years)" hint="Jobs needing more than your years plus this are disqualified.">
          <NumberInput value={p.max_experience_gap_years} min={0} step="0.5" onChange={(v) => setP({ ...p, max_experience_gap_years: v ?? 0 })} />
        </Field>
        <div className="flex items-end">
          <Tick label="On-site only in preferred locations" checked={p.onsite_only_in_preferred_locations} onChange={(v) => setP({ ...p, onsite_only_in_preferred_locations: v })} />
        </div>
        <Field label="Only jobs published in the last (days)" hint="Discovery skips older postings. Empty = any age. Imports are always kept.">
          <NumberInput value={p.max_posting_age_days ?? null} min={1} max={90} onChange={(v) => setP({ ...p, max_posting_age_days: v })} />
        </Field>
        <div className="flex items-end">
          <Tick label="Include jobs without a publish date" checked={!!p.include_undated} onChange={(v) => setP({ ...p, include_undated: v })} />
        </div>
      </div>
      <details className="mt-4 rounded-xl border border-slate-200 px-4 py-2 text-sm">
        <summary className="cursor-pointer py-1 font-medium text-slate-700">Advanced: how match scores are calculated</summary>
        <p className="mt-1 text-xs text-slate-500">Most people never need to change these. Weights set how much each part counts; bands set the score each label starts at.</p>
      <div className="mt-3 grid gap-4 pb-2 md:grid-cols-2">
        <div>
          <h3 className="mb-2 text-sm font-semibold">Score weights</h3>
          <div className="grid grid-cols-3 gap-2">
            {(Object.keys(p.weights) as (keyof Preferences["weights"])[]).map((k) => (
              <Field key={k} label={k.replaceAll("_", " ")}>
                <NumberInput value={p.weights[k]} min={0} onChange={(v) => setP({ ...p, weights: { ...p.weights, [k]: v ?? 0 } })} />
              </Field>
            ))}
          </div>
        </div>
        <div>
          <h3 className="mb-2 text-sm font-semibold">Score bands</h3>
          <div className="grid grid-cols-3 gap-2">
            {(["high", "good", "review"] as const).map((k) => (
              <Field key={k} label={`${k} ≥`}>
                <NumberInput value={p.thresholds[k]} min={0} max={100} onChange={(v) => setP({ ...p, thresholds: { ...p.thresholds, [k]: v ?? 0 } })} />
              </Field>
            ))}
          </div>
        </div>
      </div>
      </details>
      <SaveRow
        label="Save preferences"
        busy={save.isPending}
        error={save.error}
        saved={save.isSuccess && "Preferences saved. New jobs use them; use Re-check match on a job to update its score."}
        onSave={() => save.mutate()}
      />
    </Card>
    </Collapsible>
  );
}

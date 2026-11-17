import { useQuery } from "@tanstack/react-query";
import { Download, Plus } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { api, qs } from "../api/client";
import type { JobList, Source } from "../api/types";
import { FILTER_KEYS, JobFilters, type FilterKey, type FilterValues } from "../components/JobFilters";
import {
  Alert,
  Badge,
  Button,
  Card,
  ErrorText,
  Field,
  Loading,
  Modal,
  PageHeader,
  Pager,
  ScoreBadge,
  Select,
  StatusBadge,
  TextArea,
  TextInput,
  formatDate,
  sourceLabel,
  useAction,
} from "../components/ui";

const PAGE_SIZE = 50;
const MODE_TEXT: Record<string, string> = { remote: "Remote", hybrid: "Hybrid", onsite: "On-site" };

// "Bengaluru · Hybrid". When the posting's location already names a work mode, trust it as written
// rather than adding a second (sometimes contradictory) one.
function place(location: string | null, mode: string | null): string {
  const m = mode ? (MODE_TEXT[mode] ?? mode) : null;
  if (!location) return m ?? "Location not stated";
  if (!m || /remote|hybrid|on-?site/i.test(location)) return location;
  return `${location} · ${m}`;
}

export function JobsPage() {
  const [params, setParams] = useSearchParams();
  const [importing, setImporting] = useState(false);
  const values = Object.fromEntries(FILTER_KEYS.map((f) => [f, params.get(f) ?? ""])) as FilterValues;
  const page = Number(values.page || 1);
  const jobs = useQuery({
    queryKey: ["jobs", params.toString()],
    queryFn: () => api<JobList>(`/jobs${qs({ ...values, page, page_size: PAGE_SIZE, sort: values.sort || "score" })}`),
  });
  const sources = useQuery({ queryKey: ["sources"], queryFn: () => api<Source[]>("/sources") });

  function update(patch: Partial<FilterValues>) {
    const next = new URLSearchParams(params);
    for (const [key, value] of Object.entries(patch)) {
      if (value) next.set(key, value);
      else next.delete(key);
    }
    if (!("page" in patch)) next.delete("page"); // any new filter starts from page 1
    setParams(next, { replace: true });
  }
  const set = (key: FilterKey, value: string) => update({ [key]: value });
  const items = jobs.data?.items ?? [];
  const hasSalary = items.some((j) => j.salary_text);
  const hasExperience = items.some((j) => j.experience_min !== null);

  return (
    <>
      <PageHeader
        title="Job Discovery"
        subtitle="Jobs found for you, best matches first."
        actions={
          <>
            <a href={`/api/jobs/export.csv${qs({ status: values.status, min_score: values.min_score })}`} className="hidden items-center sm:inline-flex gap-1.5 rounded-lg border border-slate-200 bg-white px-3.5 py-2 text-sm font-medium text-slate-700 shadow-xs transition hover:bg-slate-50">
              <Download className="size-4" aria-hidden /> Export CSV
            </a>
            <Button variant="primary" onClick={() => setImporting(true)}>
              <Plus className="size-4" aria-hidden /> Import job
            </Button>
          </>
        }
      />
      <JobFilters
        values={values}
        total={jobs.data?.total}
        sources={sources.data ?? []}
        onChange={update}
        onClear={() => setParams({}, { replace: true })}
      />

      {jobs.isLoading ? (
        <Loading />
      ) : jobs.error ? (
        <ErrorText error={jobs.error} />
      ) : (
        <Card>
          {/* Phones: one card per job. Wider screens: the table (columns that are empty on this page are left out). */}
          <ul className="divide-y divide-slate-100 xl:hidden">
            {jobs.data!.items.map((job) => (
              <li key={job.id} className="py-3 first:pt-0">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <Link to={`/jobs/${job.id}`} className="font-medium leading-snug text-indigo-700 hover:underline">
                      {job.title}
                    </Link>
                    <div className="truncate text-sm text-slate-600">{job.company}</div>
                  </div>
                  <ScoreBadge score={job.score} band={job.band} />
                </div>
                <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-500">
                  <span>{place(job.location, job.work_mode)}</span>
                  {job.salary_text && <span>{job.salary_text}</span>}
                  {job.experience_min !== null && <span>{job.experience_min}+ yrs</span>}
                  <span>Posted {formatDate(job.posted_at)}</span>
                </div>
                <div className="mt-2 flex flex-wrap gap-1">
                  <StatusBadge status={job.status} />
                  {job.flags.suspicious && <Badge tone="red">suspicious</Badge>}
                  {job.flags.prompt_injection && <Badge tone="red" title="The posting contains hidden text aimed at AI tools">hidden instructions — review</Badge>}
                  {job.flags.email_available && <Badge tone="green">email available</Badge>}
                  {job.liveness === "expired" && <Badge>expired</Badge>}
                </div>
              </li>
            ))}
            {jobs.data!.items.length === 0 && <li className="py-6 text-center text-sm text-slate-500">No jobs match. Run discovery from the Dashboard or import a job.</li>}
          </ul>
          <div className="hidden overflow-x-auto xl:block">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-slate-200 text-xs uppercase text-slate-500">
                <tr>
                  <th className="py-2 pr-3">Score</th>
                  <th className="py-2 pr-3">Job</th>
                  <th className="py-2 pr-3">Location</th>
                  {hasSalary && <th className="py-2 pr-3">Salary</th>}
                  {hasExperience && <th className="py-2 pr-3">Experience</th>}
                  <th className="py-2 pr-3">Found via</th>
                  <th className="py-2 pr-3">Status</th>
                  <th className="py-2 pr-3">Posted</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {jobs.data!.items.map((job) => (
                  <tr key={job.id} className="align-top hover:bg-slate-50">
                    <td className="py-2 pr-3">
                      <ScoreBadge score={job.score} band={job.band} />
                    </td>
                    <td className="py-2 pr-3">
                      <Link to={`/jobs/${job.id}`} className="font-medium text-indigo-700 hover:underline">
                        {job.title}
                      </Link>
                      <div className="text-slate-600">{job.company}</div>
                      <div className="mt-0.5 flex flex-wrap gap-1">
                        {job.flags.prompt_injection && <Badge tone="red" title="The posting contains hidden text aimed at AI tools">hidden instructions — review</Badge>}
                        {job.flags.suspicious && <Badge tone="red">suspicious</Badge>}
                        {job.flags.duplicate && <Badge tone="amber">duplicate listing</Badge>}
                        {job.flags.repost && <Badge tone="amber">repost</Badge>}
                        {job.flags.email_available && <Badge tone="green">email available</Badge>}
                        {job.liveness === "expired" && <Badge>expired</Badge>}
                      </div>
                    </td>
                    <td className="py-2 pr-3 text-slate-600">{place(job.location, job.work_mode)}</td>
                    {hasSalary && <td className="py-2 pr-3 text-slate-600">{job.salary_text ?? "—"}</td>}
                    {hasExperience && <td className="py-2 pr-3 text-slate-600">{job.experience_min !== null ? `${job.experience_min}+ yrs` : "—"}</td>}
                    <td className="py-2 pr-3 text-slate-600">{sourceLabel(job.source, job.flags.via)}</td>
                    <td className="py-2 pr-3">
                      <StatusBadge status={job.status} />
                    </td>
                    <td className="py-2 pr-3 text-slate-600">{formatDate(job.posted_at)}</td>
                  </tr>
                ))}
                {jobs.data!.items.length === 0 && (
                  <tr>
                    <td colSpan={6 + Number(hasSalary) + Number(hasExperience)} className="py-6 text-center text-slate-500">
                      No jobs match. Run discovery from the Dashboard or import a job.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          <Pager page={page} total={jobs.data!.total} pageSize={PAGE_SIZE} onPage={(p) => set("page", String(p))} />
        </Card>
      )}
      {importing && <ImportDialog onClose={() => setImporting(false)} />}
    </>
  );
}

type FetchedJob = {
  url: string;
  source: string;
  title: string;
  company: string;
  description: string;
  location: string | null;
  work_mode: string | null;
  apply_email: string | null;
  questions: string[];
  posted_at: string | null;
  missing: string[];
  warnings: string[];
};

const SOURCE_LABEL: Record<string, string> = {
  greenhouse: "the Greenhouse job board",
  lever: "the Lever job board",
  ashby: "the Ashby job board",
  smartrecruiters: "SmartRecruiters",
  jsonld: "the page's structured job data",
  page: "the page text",
};

function ImportDialog({ onClose }: { onClose: () => void }) {
  const navigate = useNavigate();
  const [form, setForm] = useState({ title: "", company: "", url: "", description: "", location: "", work_mode: "", apply_email: "", recruiter_name: "", recruiter_email: "", questions: "" });
  const save = useAction(
    () =>
      api<{ id: number }>("/jobs/import", {
        method: "POST",
        body: {
          ...form,
          location: form.location || null,
          work_mode: form.work_mode || null,
          apply_email: form.apply_email || null,
          recruiter_name: form.recruiter_name || null,
          recruiter_email: form.recruiter_email || null,
          questions: form.questions.split("\n").map((q) => q.trim()).filter(Boolean),
        },
      }),
    (r) => navigate(`/jobs/${r.id}`),
  );
  const [fetched, setFetched] = useState<FetchedJob | null>(null);
  const fetchJob = useAction(
    () => api<FetchedJob>("/jobs/fetch", { method: "POST", body: { url: form.url } }),
    (r) => {
      setFetched(r);
      // Fill only what the page provided; anything you already typed stays.
      setForm((f) => ({
        ...f,
        url: r.url || f.url,
        title: f.title || r.title,
        company: f.company || r.company,
        description: f.description || r.description,
        location: f.location || r.location || "",
        work_mode: f.work_mode || r.work_mode || "",
        apply_email: f.apply_email || r.apply_email || "",
        questions: f.questions || r.questions.join("\n"),
      }));
    },
  );
  const bind = (key: keyof typeof form) => ({ value: form[key], onChange: (e: { target: { value: string } }) => setForm({ ...form, [key]: e.target.value }) });
  return (
    <Modal title="Import a job" onClose={onClose}>
      <p className="mb-3 text-sm text-slate-600">
        Paste the posting link and choose <b>Fetch</b>: the agent reads company career pages and Greenhouse, Lever, Ashby and SmartRecruiters links and fills the form. LinkedIn, Naukri, Indeed and similar boards do not allow
        automated reading, so paste those descriptions yourself. Check every field before importing.
      </p>
      <div className="mb-3 flex items-end gap-2">
        <Field label="Job URL" className="flex-1">
          <TextInput required type="url" placeholder="https://" {...bind("url")} />
        </Field>
        <Button onClick={() => fetchJob.mutate()} busy={fetchJob.isPending} disabled={!form.url.startsWith("https://")}>
          Fetch
        </Button>
      </div>
      {form.url && !form.url.startsWith("https://") && (
        <p className="-mt-2 mb-3 text-xs text-slate-500">Fetch needs a link that starts with https://</p>
      )}
      <ErrorText error={fetchJob.error} />
      {fetched && (
        <div className="mb-3 space-y-2">
          <Alert tone={fetched.missing.length || fetched.warnings.length ? "warning" : "success"}>
            Filled from {SOURCE_LABEL[fetched.source] ?? fetched.source}
            {fetched.posted_at ? `, posted ${formatDate(fetched.posted_at)}` : ""}.
            {fetched.missing.length > 0 && ` Not found: ${fetched.missing.join(", ")}. Add them below.`}
          </Alert>
          {fetched.warnings.map((w) => (
            <Alert key={w} tone="warning">
              {w}
            </Alert>
          ))}
        </div>
      )}
      <form
        className="grid gap-3 md:grid-cols-2"
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate();
        }}
      >
        <Field label="Job title">
          <TextInput required {...bind("title")} />
        </Field>
        <Field label="Company">
          <TextInput required {...bind("company")} />
        </Field>
        <Field label="Location">
          <TextInput {...bind("location")} />
        </Field>
        <Field label="Work mode">
          <Select {...bind("work_mode")}>
            <option value="">Not stated</option>
            <option value="remote">Remote</option>
            <option value="hybrid">Hybrid</option>
            <option value="onsite">On-site</option>
          </Select>
        </Field>
        <Field label="Job description" className="md:col-span-2">
          <TextArea required minLength={30} rows={8} {...bind("description")} />
        </Field>
        <Field label="Application email (only if the posting asks for it)">
          <TextInput type="email" {...bind("apply_email")} />
        </Field>
        <Field label="Recruiter email (only if publicly listed)">
          <TextInput type="email" {...bind("recruiter_email")} />
        </Field>
        <Field label="Recruiter name">
          <TextInput {...bind("recruiter_name")} />
        </Field>
        <Field label="Application form questions" hint="One per line" className="md:col-span-2">
          <TextArea rows={3} {...bind("questions")} />
        </Field>
        <div className="md:col-span-2">
          <ErrorText error={save.error} />
        </div>
        <div className="flex flex-wrap items-center justify-end gap-2 md:col-span-2">
          {!form.url && <span className="mr-auto text-xs text-slate-500">Add the job URL above to import.</span>}
          <Button onClick={onClose}>Cancel</Button>
          <Button type="submit" variant="primary" busy={save.isPending} disabled={!form.url}>
            Import and score
          </Button>
        </div>
      </form>
    </Modal>
  );
}

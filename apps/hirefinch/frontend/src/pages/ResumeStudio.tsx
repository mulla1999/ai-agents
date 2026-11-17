import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, ChevronRight, Download, FileText, Search } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { api } from "../api/client";
import type { ResumeJob, ResumeVersionFull, ResumeVersionSummary } from "../api/types";
import { Alert, Badge, Button, Card, Empty, ErrorText, List, Loading, PageHeader, Pre, ScoreBadge, cx, formatDate, useAction } from "../components/ui";

type JobGroup = { jobId: number; latest: ResumeVersionSummary; count: number };

/** One entry per job: its newest version, and how many versions exist. */
function groupByJob(versions: ResumeVersionSummary[]): JobGroup[] {
  const groups = new Map<number, JobGroup>();
  for (const v of versions) {
    const g = groups.get(v.job_id);
    if (!g) groups.set(v.job_id, { jobId: v.job_id, latest: v, count: 1 });
    else {
      g.count += 1;
      if (v.version_no > g.latest.version_no) g.latest = v;
    }
  }
  return [...groups.values()].sort((a, b) => b.latest.created_at.localeCompare(a.latest.created_at));
}

const jobTitle = (v: { job?: ResumeJob | null; job_id: number }) => v.job?.title ?? `Job #${v.job_id}`;

export function ResumeStudioPage() {
  const { versionId } = useParams();
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const versions = useQuery({ queryKey: ["versions"], queryFn: () => api<ResumeVersionSummary[]>("/resumes/versions") });
  const groups = groupByJob(versions.data ?? []);
  const q = query.trim().toLowerCase();
  const shown = q ? groups.filter((g) => `${g.latest.job?.title ?? ""} ${g.latest.job?.company ?? ""}`.toLowerCase().includes(q)) : groups;
  // Wide screens show the newest resume beside the list; phones show the list until you pick one.
  const selected = versionId ?? (groups[0] ? String(groups[0].latest.id) : undefined);
  const selectedJob = versions.data?.find((v) => String(v.id) === selected)?.job_id;

  useEffect(() => {
    if (versionId) window.scrollTo({ top: 0 });
  }, [versionId]);

  return (
    <>
      <div className={cx(versionId && "hidden lg:block")}>
        <PageHeader
          title="Resume Studio"
          subtitle="A resume tailored for each job, built only from your real experience. Pick a job to see its resume."
          actions={
            <Link to="/resume-builder" className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3.5 py-2 text-sm font-medium text-slate-700 shadow-xs hover:bg-slate-50">
              Improve your main resume
            </Link>
          }
        />
      </div>
      <div className="grid gap-4 lg:grid-cols-[22rem_1fr]">
        <section className={cx("min-w-0", versionId && "hidden lg:block")}>
          <div className="lg:sticky lg:top-6">
            <label className="relative mb-3 block">
              <span className="sr-only">Search resumes</span>
              <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-slate-400" aria-hidden />
              <input
                type="search"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search by job or company"
                className="w-full rounded-xl border border-slate-200 bg-white py-2.5 pl-9 pr-3 text-sm placeholder:text-slate-400 focus:border-indigo-500 focus:outline-none focus:ring-4 focus:ring-indigo-500/10"
              />
            </label>
            {versions.isLoading ? (
              <Loading />
            ) : versions.error ? (
              <ErrorText error={versions.error} />
            ) : groups.length === 0 ? (
              <Empty>No tailored resumes yet. Open a job in Job Discovery and choose “Generate resume”, or ask the assistant to apply.</Empty>
            ) : (
              <ul className="scroll-soft space-y-2 lg:max-h-[calc(100vh-11rem)] lg:overflow-y-auto lg:pr-1">
                {shown.map((g) => {
                  const v = g.latest;
                  const active = g.jobId === selectedJob;
                  return (
                    <li key={g.jobId}>
                      <button
                        type="button"
                        onClick={() => navigate(`/resumes/${v.id}`)}
                        className={cx(
                          "w-full rounded-xl border bg-white p-3 text-left shadow-xs transition hover:border-indigo-300 hover:shadow-soft",
                          active ? "border-indigo-400 ring-2 ring-indigo-500/15" : "border-slate-200",
                        )}
                      >
                        <div className="flex items-start justify-between gap-2">
                          <div className="min-w-0">
                            <p className="font-medium leading-snug text-slate-900">{jobTitle(v)}</p>
                            <p className="truncate text-sm text-slate-600">
                              {v.job?.company ?? "—"}
                              {v.job?.location ? ` · ${v.job.location}` : ""}
                            </p>
                          </div>
                          {v.job?.score != null && <ScoreBadge score={v.job.score} band={v.job.band} />}
                        </div>
                        <div className="mt-2 flex flex-wrap items-center gap-1.5 text-xs text-slate-500">
                          <Badge tone={v.valid ? "green" : "red"}>{v.valid ? "ready to send" : "needs fixing"}</Badge>
                          <span>
                            {formatDate(v.created_at)} · {g.count > 1 ? `${g.count} versions` : "1 version"}
                          </span>
                          <ChevronRight className="ml-auto size-4 text-slate-300" aria-hidden />
                        </div>
                      </button>
                    </li>
                  );
                })}
                {shown.length === 0 && <li className="px-1 py-4 text-sm text-slate-500">No resumes match “{query}”.</li>}
              </ul>
            )}
          </div>
        </section>
        <section className={cx("min-w-0", !versionId && "hidden lg:block")}>
          {versionId && (
            <Link to="/resumes" className="mb-3 inline-flex items-center gap-1 text-sm font-medium text-indigo-700 lg:hidden">
              <ArrowLeft className="size-4" aria-hidden /> All resumes
            </Link>
          )}
          {selected ? <VersionView id={selected} /> : null}
        </section>
      </div>
    </>
  );
}

function VersionView({ id }: { id: string }) {
  const query = useQuery({ queryKey: ["version", id], queryFn: () => api<ResumeVersionFull>(`/resumes/versions/${id}`) });
  const [tab, setTab] = useState<"preview" | "compare" | "diff">("preview");
  // The PDF is generated once and stored; if the stored file is gone, say so instead of showing the
  // server's error inside the preview.
  const file = useQuery({
    queryKey: ["version-file", id],
    queryFn: async () => {
      const r = await fetch(`/api/resumes/versions/${id}/download?format=pdf`, { credentials: "same-origin" });
      if (r.ok) return { ok: true as const };
      const body = (await r.json().catch(() => ({}))) as { message?: string };
      return { ok: false as const, message: body.message ?? `HTTP ${r.status}` };
    },
    staleTime: 60_000,
  });
  const regenerate = useAction(() => api(`/jobs/${query.data!.job_id}/tailor`, { method: "POST" }));
  if (query.isLoading) return <Loading />;
  if (query.error) return <ErrorText error={query.error} />;
  const v = query.data!;
  const report = v.report;
  const download = (format: "pdf" | "docx") => `/api/resumes/versions/${v.id}/download?format=${format}`;
  const downloadButton = (format: "pdf" | "docx", label: string) => (
    <a className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-sm font-medium text-slate-700 shadow-xs hover:bg-slate-50" href={download(format)} download>
      <Download className="size-4" aria-hidden /> {label}
    </a>
  );
  return (
    <div className="min-w-0 space-y-4">
      <Card>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="text-xs font-medium uppercase tracking-wide text-slate-400">Resume for</p>
            <h2 className="text-lg font-semibold leading-snug tracking-tight text-slate-900">{jobTitle(v)}</h2>
            <p className="text-sm text-slate-600">
              {v.job?.company}
              {v.job?.location ? ` · ${v.job.location}` : ""}
            </p>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              {v.job?.score != null && <ScoreBadge score={v.job.score} band={v.job.band} />}
              {file.data && !file.data.ok ? (
                <Badge tone="red">file missing</Badge>
              ) : (
                <Badge tone={v.valid ? "green" : "red"}>{v.valid ? "ready to send" : "needs fixing"}</Badge>
              )}
              <Link to={`/jobs/${v.job_id}`} className="text-sm text-indigo-700 hover:underline">
                View job
              </Link>
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            {downloadButton("pdf", "PDF")}
            {downloadButton("docx", "Word")}
          </div>
        </div>
        {(v.versions ?? []).length > 1 && (
          <div className="mt-3 flex flex-wrap items-center gap-1.5 border-t border-slate-100 pt-3 text-xs">
            <span className="text-slate-500">Versions:</span>
            {v.versions!.map((x) => (
              <Link
                key={x.id}
                to={`/resumes/${x.id}`}
                className={cx("rounded-full px-2.5 py-1 font-medium", x.id === v.id ? "bg-indigo-600 text-white" : "bg-slate-100 text-slate-700 hover:bg-slate-200")}
              >
                v{x.version_no} · {formatDate(x.created_at)}
              </Link>
            ))}
          </div>
        )}
        {file.data && !file.data.ok && (
          <div className="mt-3">
            <Alert tone="error">
              <p>The file for this resume is missing, so it can't be previewed or sent. Make a new version for this job: it takes a few seconds.</p>
              <Button className="mt-2" variant="primary" busy={regenerate.isPending} onClick={() => regenerate.mutate()}>
                Make a new version
              </Button>
              {regenerate.isSuccess && <p className="mt-2">Done. The new version is listed under Versions.</p>}
              <ErrorText error={regenerate.error} />
            </Alert>
          </div>
        )}
        {!v.validation.passed && (
          <div className="mt-3">
            <Alert tone="error">
              This version failed a check, so it will not be sent. Generate a new one from the job page.
              <List items={v.validation.errors} />
            </Alert>
          </div>
        )}
      </Card>

      <Card
        actions={
          <div role="tablist" className="flex gap-1">
            {(["preview", "compare", "diff"] as const).map((t) => (
              <button
                key={t}
                role="tab"
                aria-selected={tab === t}
                type="button"
                onClick={() => setTab(t)}
                className={cx("rounded-lg px-3 py-1 text-sm", tab === t ? "bg-indigo-600 text-white" : "text-slate-600 hover:bg-slate-100")}
              >
                {t === "preview" ? "Resume" : t === "compare" ? "Side by side" : "Changes"}
              </button>
            ))}
          </div>
        }
        title="Resume"
      >
        {tab === "preview" && (
          <>
            {/* Phones often cannot show a PDF inside a page: open it, and read the text here. */}
            <div className="md:hidden">
              <a href={download("pdf")} target="_blank" rel="noopener noreferrer" className="mb-3 flex items-center justify-center gap-2 rounded-xl bg-gradient-to-b from-indigo-500 to-indigo-600 px-4 py-2.5 text-sm font-medium text-white shadow-sm">
                <FileText className="size-4" aria-hidden /> Open PDF
              </a>
              <Pre className="max-h-none font-sans text-[0.8125rem] leading-relaxed">{v.text}</Pre>
            </div>
            {file.data?.ok ? (
              <iframe title="Tailored resume PDF" src={download("pdf")} className="hidden h-[80vh] w-full rounded-lg border border-slate-200 md:block" />
            ) : (
              <div className="hidden md:block">
                {file.isLoading ? <Loading /> : <Pre className="max-h-none font-sans text-[0.8125rem] leading-relaxed">{v.text}</Pre>}
              </div>
            )}
          </>
        )}
        {tab === "compare" && (
          <div className="grid gap-3 md:grid-cols-2">
            <div>
              <h3 className="mb-1 text-sm font-semibold">Your master resume</h3>
              <Pre>{v.master_text}</Pre>
            </div>
            <div>
              <h3 className="mb-1 text-sm font-semibold">Tailored for this job</h3>
              <Pre>{v.text}</Pre>
            </div>
          </div>
        )}
        {tab === "diff" && <Diff text={report.diff} />}
      </Card>

      <Card title="What was changed for this job">
        <div className="grid gap-4 md:grid-cols-2">
          <div>
            <h3 className="mb-1 text-sm font-semibold">Changes</h3>
            <List items={report.changes} />
          </div>
          <div>
            <h3 className="mb-1 text-sm font-semibold">Keyword coverage</h3>
            <div className="flex flex-wrap gap-1">
              {report.keyword_coverage.covered.map((k) => (
                <Badge key={k} tone="green">
                  {k}
                </Badge>
              ))}
              {report.keyword_coverage.missing_but_verified.map((k) => (
                <Badge key={k} tone="amber" title="verified but not shown">
                  {k}
                </Badge>
              ))}
              {report.keyword_coverage.missing_not_in_profile.map((k) => (
                <Badge key={k} tone="red" title="not in your profile, not added">
                  {k}
                </Badge>
              ))}
            </div>
            <p className="mt-1 text-xs text-slate-500">Green: present. Red: the job asks for it but your resume does not evidence it, so it was not added.</p>
          </div>
          <div>
            <h3 className="mb-1 text-sm font-semibold">Gaps</h3>
            <List items={report.gaps} empty="No gaps" />
          </div>
          <div>
            <h3 className="mb-1 text-sm font-semibold">Omitted bullets</h3>
            <List items={report.omitted_bullets.map((b) => `${b.section}: ${b.text}`)} empty="Nothing omitted" />
          </div>
        </div>
        {(report.rewrites ?? []).length > 0 && (
          <div className="mt-5 border-t border-slate-100 pt-4">
            <h3 className="mb-1 text-sm font-semibold">Bullets reworded by AI ({report.rewrites!.length})</h3>
            <p className="mb-3 text-xs text-slate-500">Each keeps every number and technology of your original and claims nothing new; anything else was rejected and your wording kept.</p>
            <ul className="space-y-3">
              {report.rewrites!.map((r, i) => (
                <li key={i} className="grid gap-2 text-sm md:grid-cols-2">
                  <p className="rounded-lg bg-slate-50 p-2.5 text-slate-500 ring-1 ring-slate-200">
                    <span className="mb-0.5 block text-[0.6875rem] font-semibold uppercase tracking-wide text-slate-400">Your master</span>
                    {r.original}
                  </p>
                  <p className="rounded-lg bg-emerald-50/60 p-2.5 text-slate-800 ring-1 ring-emerald-200">
                    <span className="mb-0.5 block text-[0.6875rem] font-semibold uppercase tracking-wide text-emerald-600">In this resume</span>
                    {r.rewritten}
                  </p>
                </li>
              ))}
            </ul>
          </div>
        )}
        {(report.rejected_rewrites ?? []).length > 0 && (
          <details className="mt-3 text-sm">
            <summary className="cursor-pointer text-slate-600">AI rewordings rejected ({report.rejected_rewrites!.length}): your original wording was kept</summary>
            <ul className="mt-2 space-y-2">
              {report.rejected_rewrites!.map((r, i) => (
                <li key={i} className="rounded-lg bg-amber-50/60 p-2.5 text-xs text-slate-700 ring-1 ring-amber-200">
                  <span className="font-medium text-amber-800">{r.reason}:</span> {r.proposed}
                </li>
              ))}
            </ul>
          </details>
        )}
        {report.llm && report.llm !== "not used" && <p className="mt-3 text-xs text-slate-500">Written with: {report.llm}</p>}
        <details className="mt-3 border-t border-slate-100 pt-3 text-sm">
          <summary className="cursor-pointer text-slate-600">
            Quality checks: {v.validation.checks.filter((c) => c.passed).length} of {v.validation.checks.length} passed
            {v.validation.warnings.length > 0 && `, ${v.validation.warnings.length} note${v.validation.warnings.length === 1 ? "" : "s"}`}
          </summary>
          {v.validation.warnings.length > 0 && (
            <div className="mt-2">
              <Alert tone="warning">
                <List items={v.validation.warnings} />
              </Alert>
            </div>
          )}
          <ul className="mt-2 space-y-1">
            {v.validation.checks.map((c) => (
              <li key={c.name} className="flex gap-2">
                <Badge tone={c.passed ? "green" : c.severity === "error" ? "red" : "amber"}>{c.passed ? "pass" : c.severity}</Badge>
                <span>{c.name}</span>
                {!c.passed && <span className="text-slate-500">— {c.detail}</span>}
              </li>
            ))}
          </ul>
          <p className="mt-2 break-all text-xs text-slate-400">PDF SHA-256 {v.pdf_sha256}</p>
        </details>
      </Card>

    </div>
  );
}

function Diff({ text }: { text: string }) {
  if (!text.trim()) return <Empty>No differences.</Empty>;
  return (
    <pre className="max-h-[40rem] overflow-auto rounded-md bg-slate-50 p-3 text-xs ring-1 ring-slate-200">
      {text.split("\n").map((line, i) => (
        <div
          key={i}
          className={cx(
            "whitespace-pre-wrap break-words",
            line.startsWith("+") && !line.startsWith("+++") && "bg-emerald-50 text-emerald-800",
            line.startsWith("-") && !line.startsWith("---") && "bg-red-50 text-red-800",
            line.startsWith("@@") && "text-indigo-600",
          )}
        >
          {line || " "}
        </div>
      ))}
    </pre>
  );
}

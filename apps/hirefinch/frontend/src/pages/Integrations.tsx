import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api/client";
import type { IntegrationKind, IntegrationView, Integrations, Source, TestResult } from "../api/types";
import { AdzunaForm, EmailForm, ImapForm, JoobleForm,
  WebSearchForm, LlmForm, type ConnectionActions } from "../components/ConnectionForms";
import { ChevronDown, Plus, Search } from "lucide-react";
import { Alert, Badge, Button, Card, Checkbox, Collapsible, ErrorText, Field, Loading, NumberInput, PageHeader, TextArea, TextInput, cx, formatDate, useAction } from "../components/ui";

const SUPPORT_TONE = { implemented: "green", needs_credentials: "amber", manual: "blue", unsupported: "slate" } as const;
const SUPPORT_LABEL = { implemented: "ready", needs_credentials: "needs a key", manual: "manual", unsupported: "not available" } as const;

// What each connection is for, shown while its section is closed.
const PURPOSE: Record<IntegrationKind, string> = {
  email: "Sends your applications, recruiter emails and notifications.",
  llm: "Writes your tailored resumes, answers and emails.",
  imap: "Reads LinkedIn, Naukri, Indeed and Hirist job alerts from your inbox.",
  adzuna: "Adds job listings from Adzuna (free key).",
  jooble: "Adds job listings from Jooble (free key).",
  websearch: "Lets the assistant look things up on the web.",
};

const EMPTY_VIEW = (kind: string): IntegrationView => ({ kind, configured: false, config: {}, secrets_set: [] });

// Example configuration shown under each source's JSON editor.
const SOURCE_EXAMPLES: Record<string, string> = {
  greenhouse: '{"boards": [{"token": "stripe", "company": "Stripe"}], "locations": ["Bengaluru", "Pune"], "remote_country": "India"}',
  lever: '{"boards": [{"token": "meesho", "company": "Meesho"}], "locations": ["Bengaluru"], "remote_country": "India"}',
  ashby: '{"boards": [{"token": "sarvam", "company": "Sarvam AI"}], "locations": ["Bengaluru"], "remote_country": "India"}',
  smartrecruiters: '{"boards": [{"token": "swiggy", "company": "Swiggy"}], "locations": ["Bengaluru", "Mumbai"], "remote_country": "India"}',
  career_page: '{"pages": ["https://careers.example.com/jobs"]}',
  adzuna: '{"country": "in", "queries": ["java backend"], "where": "Pune"}',
  jooble: '{"queries": ["java developer", "ai engineer"], "locations": ["Bengaluru", "Pune"]}',
  themuse: '{"categories": ["Software Engineering"], "locations": ["Bengaluru, India", "Flexible / Remote"], "pages": 3}',
  job_alerts: '{"sites": ["linkedin", "naukri", "indeed", "hirist"], "folder": "INBOX"}',
};

export function IntegrationsPage() {
  const query = useQuery({ queryKey: ["integrations"], queryFn: () => api<Integrations>("/integrations") });
  if (query.isLoading) return <Loading />;
  if (query.error) return <ErrorText error={query.error} />;
  const d = query.data!;
  const sources = d.sources.filter((s) => s.configurable);
  return (
    <>
      <PageHeader
        title="Integrations"
        subtitle="Your own connections. Passwords and keys are stored encrypted and never shown again; leave a secret blank to keep the saved one."
      />
      <div className="space-y-4">
        {!d.notification_email_set && <Alert tone="info">Set a notification email in Profile to receive notifications.</Alert>}
        <SectionTitle>Essentials</SectionTitle>
        {(["email", "llm"] as const).map((k) => (
          <Section key={k} kind={k} view={d.integrations[k] ?? EMPTY_VIEW(k)} openIfMissing />
        ))}
        <SectionTitle>More jobs and tools (optional)</SectionTitle>
        {(["imap", "adzuna", "jooble", "websearch"] as const).map((k) => (
          <Section key={k} kind={k} view={d.integrations[k] ?? EMPTY_VIEW(k)} />
        ))}

        <SectionTitle>Where jobs come from</SectionTitle>
        <FindCompany />
        <Collapsible summary={`${sources.filter((s) => s.enabled).length} of ${sources.length} sources on. Open one to change what it searches.`}>
          <Card title="Job sources">
            <div className="space-y-2">
              {sources.map((s) => (
                <SourceRow key={s.key} source={s} />
              ))}
            </div>
          </Card>
        </Collapsible>

        <Collapsible summary="LinkedIn, Naukri and others that don't allow automated search, and what to do instead.">
        <Card title="Not automated">
          <p className="mb-2 text-sm text-slate-600">
            These sites have no permitted automated search. LinkedIn, Naukri, Indeed and Hirist are covered by the <strong>job-alert
            mailbox</strong> above; for any posting you can also use <strong>Import job</strong> on the Job Discovery page.
          </p>
          <ul className="space-y-1 text-sm">
            {d.unsupported.map((u) => (
              <li key={u.key}>
                <span className="font-medium">{u.name}</span> — <span className="text-slate-600">{u.reason}</span>
              </li>
            ))}
          </ul>
        </Card>
        </Collapsible>
      </div>
    </>
  );
}

function SectionTitle({ children }: { children: string }) {
  return <h2 className="px-1 pt-2 text-xs font-semibold uppercase tracking-wider text-slate-500">{children}</h2>;
}

// One connection as a collapsible card: closed it shows what it is for and whether it is connected.
// Essentials start open while they are not set up, so a new user lands on what to do first.
function Section({ kind, view, openIfMissing = false }: { kind: IntegrationKind; view: IntegrationView; openIfMissing?: boolean }) {
  // The card title already carries the configured / not set up badge.
  return (
    <Collapsible defaultOpen={openIfMissing && !view.configured} summary={PURPOSE[kind]}>
      <Connection kind={kind} view={view} />
    </Collapsible>
  );
}

type FoundBoard = { kind: string; token: string; company: string; jobs: number; india_jobs: number | null; added: boolean };
const BOARD_NAME: Record<string, string> = { greenhouse: "Greenhouse", lever: "Lever", ashby: "Ashby", smartrecruiters: "SmartRecruiters" };

// Follow any company that publishes its openings on Greenhouse, Lever, Ashby or SmartRecruiters.
export function FindCompany() {
  const [q, setQ] = useState("");
  const [added, setAdded] = useState<string[]>([]);
  const search = useAction((text: string) => api<{ results: FoundBoard[] }>(`/sources/find-company?q=${encodeURIComponent(text)}`));
  const add = useAction(
    (b: FoundBoard) =>
      api(`/sources/${b.kind}/boards`, { method: "POST", body: { token: b.token, company: b.company } }).then(() => `${b.kind}:${b.token}`),
    (id) => setAdded((list) => [...list, id]),
  );
  const results = search.data?.results;
  return (
    <Card title="Find a company">
      <form
        className="flex flex-col gap-2 sm:flex-row"
        onSubmit={(e) => {
          e.preventDefault();
          if (q.trim().length >= 2) search.mutate(q.trim());
        }}
      >
        <TextInput aria-label="Company name or careers link" placeholder="Company name or careers link, e.g. Razorpay" value={q}
          onChange={(e) => setQ(e.target.value)} className="flex-1" />
        <Button type="submit" variant="primary" busy={search.isPending} disabled={q.trim().length < 2}>
          <Search className="size-4" aria-hidden /> Find
        </Button>
      </form>
      <p className="mt-2 text-xs text-slate-500">
        Checks Greenhouse, Lever, Ashby and SmartRecruiters, where many companies publish their openings. Once added, its new jobs
        arrive with every search.
      </p>
      {results && results.length === 0 && (
        <div className="mt-3">
          <Alert tone="info">
            No job board found for “{search.variables}”. Try the exact company name, or paste a job link from its careers page. Companies
            on other systems: use Import job on Job Discovery, or your LinkedIn and Naukri alerts.
          </Alert>
        </div>
      )}
      {results && results.length > 0 && (
        <ul className="mt-3 divide-y divide-slate-100 rounded-xl border border-slate-200">
          {results.map((b) => {
            const done = b.added || added.includes(`${b.kind}:${b.token}`);
            return (
              <li key={`${b.kind}:${b.token}`} className="flex flex-wrap items-center gap-2 p-3">
                <span className="min-w-0 flex-1">
                  <span className="font-medium">{b.company}</span>
                  <span className="block text-xs text-slate-500">
                    {BOARD_NAME[b.kind]} · {b.jobs} open {b.jobs === 1 ? "job" : "jobs"}
                    {b.india_jobs != null && ` · ${b.india_jobs} in India`}
                  </span>
                </span>
                {done ? (
                  <Badge tone="green">following</Badge>
                ) : (
                  <Button busy={add.isPending && add.variables === b} onClick={() => add.mutate(b)}>
                    <Plus className="size-4" aria-hidden /> Add
                  </Button>
                )}
              </li>
            );
          })}
        </ul>
      )}
      <ErrorText error={search.error || add.error} />
    </Card>
  );
}

function SourceRow({ source }: { source: Source }) {
  const [enabled, setEnabled] = useState(source.enabled);
  const [config, setConfig] = useState(JSON.stringify(source.config ?? {}, null, 2));
  const [schedule, setSchedule] = useState<number | null>(source.schedule_minutes);
  const [configError, setConfigError] = useState<string | null>(null);
  const save = useAction((body: unknown) => api(`/sources/${source.key}`, { method: "PUT", body }));
  const test = useAction(() => api<{ ok: boolean; message: string; warnings?: string[] }>(`/sources/${source.key}/test`, { method: "POST" }));
  const [open, setOpen] = useState(false);
  return (
    <div className="rounded-xl border border-slate-200">
      <button type="button" aria-expanded={open} onClick={() => setOpen(!open)} className="flex w-full items-center gap-2 rounded-xl p-3 text-left hover:bg-slate-50">
        <span className="min-w-0 flex-1">
          <span className="flex flex-wrap items-center gap-2">
            <span className="font-medium">{source.name}</span>
            <Badge tone={source.enabled ? "green" : "slate"}>{source.enabled ? "on" : "off"}</Badge>
            {source.support !== "implemented" && <Badge tone={SUPPORT_TONE[source.support]}>{SUPPORT_LABEL[source.support]}</Badge>}
            {source.auth_ok === false && <Badge tone="red">key rejected</Badge>}
          </span>
          <span className="mt-0.5 block text-xs text-slate-500">
            {source.last_run_at ? `Last searched ${formatDate(source.last_run_at, true)}` : "Not searched yet"}
            {source.last_error ? " · last search had a problem" : ""}
          </span>
        </span>
        <ChevronDown className={cx("size-4 shrink-0 text-slate-400 transition", open && "rotate-180")} aria-hidden />
      </button>
      <div hidden={!open} className="border-t border-slate-100 p-3">
      <p className="text-sm text-slate-600">{source.description}</p>
      {source.last_error && <p className="mt-1 text-xs text-red-700">{source.last_error}</p>}
      <div className="mt-2 grid gap-3 md:grid-cols-[1fr_12rem]">
        <Field label="Configuration (JSON)" hint={SOURCE_EXAMPLES[source.key] ? <>Example: <code className="break-all">{SOURCE_EXAMPLES[source.key]}</code></> : undefined}>
          <TextArea rows={4} className="font-mono text-xs" value={config} onChange={(e) => setConfig(e.target.value)} />
        </Field>
        <div className="space-y-2">
          <Checkbox label="Enabled" checked={enabled} onChange={setEnabled} />
          <Field label="Schedule (minutes)" hint="Empty = automation default">
            <NumberInput value={schedule} min={15} onChange={setSchedule} />
          </Field>
        </div>
      </div>
      {configError && <Alert tone="error">{configError}</Alert>}
      <div className="mt-2 flex flex-wrap gap-2">
        <Button
          variant="primary"
          busy={save.isPending}
          onClick={() => {
            try {
              const parsed = JSON.parse(config || "{}");
              setConfigError(null);
              save.mutate({ enabled, config: parsed, schedule_minutes: schedule });
            } catch (err) {
              setConfigError(`Not valid JSON: ${(err as Error).message}`);
            }
          }}
        >
          Save
        </Button>
        <Button busy={test.isPending} onClick={() => test.mutate()}>
          Test now
        </Button>
      </div>
      {test.data && (
        <div className="mt-2">
          <Alert tone={test.data.ok ? "success" : "error"}>
            {test.data.message}
            {test.data.warnings && test.data.warnings.length > 0 && <div className="text-xs">{test.data.warnings.join("; ")}</div>}
          </Alert>
        </div>
      )}
      <ErrorText error={save.error || test.error} />
      </div>
    </div>
  );
}

function Connection({ kind, view }: { kind: IntegrationKind; view: IntegrationView }) {
  const [saved, setSaved] = useState(false);
  const save = useAction(
    ({ config, secrets }: { config: Record<string, unknown>; secrets: Record<string, string> }) =>
      api<IntegrationView>(`/integrations/${kind}`, { method: "PUT", body: { config, secrets } }),
    () => setSaved(true),
  );
  const remove = useAction(() => api(`/integrations/${kind}`, { method: "DELETE" }));
  const test = useAction(() => api<TestResult>(`/integrations/${kind}/test`, { method: "POST" }));
  const actions: ConnectionActions = {
    save: (config, secrets) => {
      setSaved(false);
      test.reset();
      save.mutate({ config, secrets });
    },
    saving: save.isPending,
    saveError: save.error,
    saved,
    remove: () => remove.mutate(),
    removing: remove.isPending,
    test: kind === "email" || kind === "llm" || kind === "websearch" ? () => test.mutate() : undefined,
    testing: test.isPending,
    testResult: test.data ?? null,
    testLabel: kind === "email" ? "Send test email" : "Test",
  };
  // Re-mount the form when the stored settings change so fields show what was saved.
  const key = JSON.stringify(view.config) + view.secrets_set.join();
  if (kind === "email") {
    return (
      <EmailForm
        key={key}
        title="Your email"
        description="Used for your notifications and, after your approval, applications and recruiter emails. Mail is sent from this account."
        view={view}
        actions={actions}
      />
    );
  }
  if (kind === "llm") return <LlmForm key={key} view={view} actions={actions} />;
  if (kind === "imap") return <ImapForm key={key} view={view} actions={actions} />;
  if (kind === "jooble") return <JoobleForm key={key} view={view} actions={actions} />;
  if (kind === "websearch") return <WebSearchForm key={key} view={view} actions={actions} />;
  return <AdzunaForm key={key} view={view} actions={actions} />;
}

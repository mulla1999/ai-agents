import { useQuery } from "@tanstack/react-query";
import { Fragment, useState } from "react";
import { Link } from "react-router";
import { api, qs } from "../api/client";
import type { AuditEvent } from "../api/types";
import { Badge, Button, Card, ErrorText, Field, JsonView, Loading, PageHeader, Pager, Select, TextInput, formatDate, statusLabel } from "../components/ui";

const PAGE_SIZE = 100;

// Filter choices: the action prefix the server filters on, in words.
const ACTION_GROUPS: [string, string][] = [
  ["job.", "Jobs"],
  ["application.", "Applications"],
  ["resume.", "Resumes"],
  ["outreach.", "Recruiter emails"],
  ["source.", "Job searches"],
  ["config.", "Profile and settings"],
  ["integration.", "Connections"],
  ["account.", "Sign-in and account"],
];

const INTEGRATION_NAMES: Record<string, string> = { llm: "AI provider", email: "Email", imap: "Job-alert mailbox", websearch: "Web search", adzuna: "Adzuna", jooble: "Jooble" };

const capitalise = (s: string) => (s ? s[0].toUpperCase() + s.slice(1) : s);
const humanise = (action: string) => capitalise(action.replaceAll(/[._]/g, " "));
const afterColon = (message: string) => (message.includes(": ") ? message.slice(message.indexOf(": ") + 2) : "");

/** Account and platform events: shown in the Activity Log, kept off the personal Dashboard feed. */
export const isHousekeeping = (e: AuditEvent) => /^(account|platform|admin|notification)\./.test(e.action);

/** An audit event as a plain sentence, with a link to what it is about when there is one. */
export function describeEvent(e: AuditEvent): { text: string; to?: string } {
  const d = (e.details ?? {}) as Record<string, unknown>;
  const job = e.entity_type === "job" && e.entity_id ? `/jobs/${e.entity_id}` : undefined;
  switch (e.action) {
    case "job.status": {
      const to = typeof d.to === "string" ? d.to : null;
      const reason = afterColon(e.message);
      return { text: to ? `A job moved to “${statusLabel(to)}”${reason ? ` (${reason})` : ""}` : capitalise(e.message), to: job };
    }
    case "job.duplicate":
      return { text: "A repeat of a job you already have was found and hidden", to: job };
    case "application.prepared":
      return { text: /needs approval/.test(e.message) ? "An application is prepared and waiting for you" : "An application is prepared", to: "/queue" };
    case "application.approved":
      return { text: "You approved an application", to: "/queue" };
    case "application.attempt":
      return { text: "HireFinch tried to send an application", to: "/tracker" };
    case "application.auto_apply":
      return { text: "Auto-apply started in your browser", to: "/queue" };
    case "resume.generated":
      return {
        text: /\(valid\)/.test(e.message) ? "A tailored resume is ready" : "A tailored resume was made but needs fixing",
        to: e.entity_id ? `/resumes/${e.entity_id}` : "/resumes",
      };
    case "resume.uploaded":
      return { text: "You uploaded a resume", to: "/profile" };
    case "outreach.drafted":
      return { text: "A recruiter email was drafted", to: "/outreach" };
    case "outreach.recomposed":
      return { text: "A recruiter email was rewritten in your new style", to: "/outreach" };
    case "outreach.cancelled":
      return { text: "A recruiter email was cancelled", to: "/outreach" };
    case "outreach.failed":
      return { text: `A recruiter email couldn't be sent${afterColon(e.message) ? `: ${afterColon(e.message)}` : ""}`, to: "/outreach" };
    case "source.run": {
      const name = e.message.split(":")[0];
      const found = /(\d+) new/.exec(e.message)?.[1];
      return { text: found !== undefined ? `${name} searched: ${found === "0" ? "no new jobs" : `${found} new job${found === "1" ? "" : "s"}`}` : capitalise(e.message), to: found && found !== "0" ? "/jobs?sort=recent" : undefined };
    }
    case "source.failed":
      return { text: `A job search didn't work: ${e.message}`, to: "/integrations" };
    case "integration.saved": {
      const kind = /^(\w+) settings/.exec(e.message)?.[1] ?? "";
      return { text: `${INTEGRATION_NAMES[kind] ?? capitalise(kind)} settings saved`, to: "/integrations" };
    }
    case "integration.email_test":
      return { text: "Test email sent", to: "/integrations" };
    case "account.login":
      return { text: "Signed in" };
    case "platform.settings": {
      const key = /'([\w]+)'/.exec(e.message)?.[1];
      return { text: key ? `Platform ${key.replaceAll("_", " ")} settings changed` : capitalise(e.message), to: "/admin/settings" };
    }
    default:
      return { text: e.message ? capitalise(e.message) : humanise(e.action), to: job };
  }
}

function LevelBadge({ level }: { level: AuditEvent["level"] }) {
  if (level === "info") return null;
  return <Badge tone={level === "error" ? "red" : "amber"}>{level === "error" ? "problem" : "warning"}</Badge>;
}

export function AuditPage() {
  const [filters, setFilters] = useState({ q: "", level: "", action: "" });
  const [applied, setApplied] = useState(filters);
  const [page, setPage] = useState(1);
  const [open, setOpen] = useState<number | null>(null);
  const query = useQuery({
    queryKey: ["audit", applied, page],
    queryFn: () => api<{ total: number; items: AuditEvent[] }>(`/audit${qs({ ...applied, page, page_size: PAGE_SIZE })}`),
  });
  const apply = () => {
    setApplied(filters);
    setPage(1);
  };
  const details = (e: AuditEvent) =>
    Object.keys(e.details ?? {}).length > 0 && (
      <Button variant="ghost" className="text-xs" aria-expanded={open === e.id} onClick={() => setOpen(open === e.id ? null : e.id)}>
        {open === e.id ? "Hide details" : "Details"}
      </Button>
    );
  return (
    <>
      <PageHeader title="Activity Log" subtitle="Everything HireFinch did for you, and every change you made." />
      <Card className="mb-4">
        <form
          className="grid grid-cols-2 gap-3 md:grid-cols-4"
          onSubmit={(e) => {
            e.preventDefault();
            apply();
          }}
        >
          <Field label="Search" className="col-span-2 md:col-span-1">
            <TextInput value={filters.q} placeholder="e.g. Deloitte" onChange={(e) => setFilters({ ...filters, q: e.target.value })} />
          </Field>
          <Field label="About">
            <Select value={filters.action} onChange={(e) => setFilters({ ...filters, action: e.target.value })}>
              <option value="">Everything</option>
              {ACTION_GROUPS.map(([prefix, label]) => (
                <option key={prefix} value={prefix}>
                  {label}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Show">
            <Select value={filters.level} onChange={(e) => setFilters({ ...filters, level: e.target.value })}>
              <option value="">All</option>
              <option value="warning">Warnings</option>
              <option value="error">Problems</option>
            </Select>
          </Field>
          <div className="col-span-2 flex items-end md:col-span-1">
            <Button type="submit" variant="primary" className="w-full md:w-auto">
              Filter
            </Button>
          </div>
        </form>
      </Card>
      {query.isLoading ? (
        <Loading />
      ) : query.error ? (
        <ErrorText error={query.error} />
      ) : (
        <Card>
          {query.data!.items.length === 0 && <p className="text-sm text-slate-500">Nothing matches these filters.</p>}
          {/* Phones: one card per event. */}
          <ul className="divide-y divide-slate-100 md:hidden">
            {query.data!.items.map((e) => {
              const { text, to } = describeEvent(e);
              return (
                <li key={e.id} className="py-3">
                  <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
                    {formatDate(e.at, true)} <LevelBadge level={e.level} />
                  </div>
                  <p className="mt-1 break-words text-sm text-slate-800">{to ? <Link to={to} className="hover:text-indigo-700 hover:underline">{text}</Link> : text}</p>
                  <div className="mt-1 flex items-center gap-2">
                    <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[0.6875rem] text-slate-500">{humanise(e.action.split(".")[0])}</span>
                    {details(e)}
                  </div>
                  {open === e.id && (
                    <div className="mt-2">
                      <JsonView value={e.details} />
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
          <div className="hidden overflow-x-auto md:block">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-slate-200 text-xs uppercase text-slate-500">
                <tr>
                  <th className="py-2 pr-3">When</th>
                  <th className="pr-3">What happened</th>
                  <th className="pr-3">About</th>
                  <th />
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {query.data!.items.map((e) => {
                  const { text, to } = describeEvent(e);
                  return (
                    <Fragment key={e.id}>
                      <tr className="align-top">
                        <td className="whitespace-nowrap py-2 pr-3 text-xs text-slate-500">{formatDate(e.at, true)}</td>
                        <td className="py-2 pr-3 text-slate-800">
                          <span className="mr-2">{to ? <Link to={to} className="hover:text-indigo-700 hover:underline">{text}</Link> : text}</span>
                          <LevelBadge level={e.level} />
                        </td>
                        <td className="whitespace-nowrap py-2 pr-3 text-xs text-slate-500">{humanise(e.action.split(".")[0])}</td>
                        <td className="py-1">{details(e)}</td>
                      </tr>
                      {open === e.id && (
                        <tr>
                          <td colSpan={4} className="pb-2">
                            <JsonView value={e.details} />
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
          <Pager page={page} total={query.data!.total} pageSize={PAGE_SIZE} onPage={setPage} />
        </Card>
      )}
    </>
  );
}

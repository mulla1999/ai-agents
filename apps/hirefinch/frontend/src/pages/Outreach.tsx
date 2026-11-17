import { useQuery } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { Link } from "react-router";
import { api } from "../api/client";
import type { Contact, Draft } from "../api/types";
import { Alert, Badge, Button, Card, Empty, ErrorText, Field, Loading, PageHeader, Select, TextArea, TextInput, formatDate, useAction } from "../components/ui";
import { Contacts } from "./JobDetail";

export function OutreachPage() {
  const query = useQuery({ queryKey: ["outreach"], queryFn: () => api<{ contacts: Contact[]; drafts: Draft[] }>("/outreach") });
  if (query.isLoading) return <Loading />;
  if (query.error) return <ErrorText error={query.error} />;
  const { contacts, drafts } = query.data!;
  return (
    <>
      <PageHeader
        title="Recruiter Outreach"
        subtitle="Email recruiters about jobs you like. Nothing is sent until you press Send (unless you turned on automatic recruiter emails)."
      />
      <div className="grid gap-4 lg:grid-cols-3">
        <Card title={`Contacts (${contacts.length})`}>
          {contacts.length === 0 ? (
            <Empty>No contacts yet. Add one from a job's page.</Empty>
          ) : (
            <div className="space-y-3">
              {groupByJob(contacts).map(([jobId, list]) => (
                <div key={jobId}>
                  <Link className="text-sm font-medium text-indigo-700 hover:underline" to={`/jobs/${jobId}`}>
                    {list[0].job_title} · {list[0].company}
                  </Link>
                  <Contacts contacts={list} />
                </div>
              ))}
            </div>
          )}
        </Card>
        <div className="space-y-4 lg:col-span-2">
          {drafts.length === 0 ? (
            <Card>
              <Empty>No emails yet. Open a job with a recruiter contact and choose Draft email.</Empty>
            </Card>
          ) : (
            <>
              {[...drafts.filter((d) => ACTIVE.includes(d.status)), ...drafts.filter((d) => d.status === "sent")].map((d) => (
                <DraftCard key={d.id} draft={d} />
              ))}
              {drafts.some((d) => d.status === "cancelled") && (
                <details className="rounded-2xl border border-slate-200/80 bg-white px-5 py-3 shadow-soft">
                  <summary className="cursor-pointer text-sm font-medium text-slate-600">Cancelled ({drafts.filter((d) => d.status === "cancelled").length})</summary>
                  <div className="mt-3 space-y-4">
                    {drafts
                      .filter((d) => d.status === "cancelled")
                      .map((d) => (
                        <DraftCard key={d.id} draft={d} />
                      ))}
                  </div>
                </details>
              )}
            </>
          )}
        </div>
      </div>
    </>
  );
}

const ACTIVE: Draft["status"][] = ["failed", "sending", "draft", "scheduled"];
const STATUS_TEXT: Record<Draft["status"], string> = {
  draft: "draft",
  scheduled: "scheduled",
  sending: "sending",
  sent: "sent",
  failed: "not sent",
  cancelled: "cancelled",
};

// Turn the last delivery error into something a person can act on.
function failureHelp(draft: Draft): ReactNode {
  const error = [...draft.deliveries].reverse().find((x) => x.error)?.error ?? "";
  if (/attachment|resume/i.test(error) && /missing|not found|changed/i.test(error)) {
    return (
      <>
        Your resume file is missing, so the email couldn't go out.{" "}
        {draft.resume_version_id ? (
          <>
            Open{" "}
            <Link className="underline" to={`/resumes/${draft.resume_version_id}`}>
              the tailored resume
            </Link>{" "}
            and regenerate it
          </>
        ) : (
          <>
            Upload your resume again in{" "}
            <Link className="underline" to="/profile">
              Profile
            </Link>
          </>
        )}
        , then try again.
      </>
    );
  }
  if (/auth|password|login|credential/i.test(error)) {
    return (
      <>
        Your email account rejected the sign-in. Check the app password in{" "}
        <Link className="underline" to="/integrations">
          Integrations
        </Link>
        , then try again.
      </>
    );
  }
  return error ? `It couldn't be sent: ${error}` : "It couldn't be sent. Try again, or cancel it.";
}

function groupByJob(contacts: Contact[]): [number, Contact[]][] {
  const map = new Map<number, Contact[]>();
  for (const c of contacts) map.set(c.job_id, [...(map.get(c.job_id) ?? []), c]);
  return [...map.entries()];
}

function DraftCard({ draft }: { draft: Draft }) {
  const [subject, setSubject] = useState(draft.subject);
  const [body, setBody] = useState(draft.body);
  const editable = draft.status === "draft";
  const save = useAction(() => api(`/outreach/drafts/${draft.id}`, { method: "PUT", body: { subject, body } }));
  const send = useAction(async () => {
    if (editable && (subject !== draft.subject || body !== draft.body)) {
      await api(`/outreach/drafts/${draft.id}`, { method: "PUT", body: { subject, body } });
    }
    return api(`/outreach/drafts/${draft.id}/send`, { method: "POST" });
  });
  const cancel = useAction(() => api(`/outreach/drafts/${draft.id}/cancel`, { method: "POST" }));
  const follow = useAction((status: string) => api(`/outreach/drafts/${draft.id}/follow-up`, { method: "POST", body: { status } }));
  const tone = draft.status === "sent" ? "green" : draft.status === "failed" ? "red" : draft.status === "cancelled" ? "slate" : "amber";
  return (
    <Card
      title={
        <span className="flex flex-wrap items-center gap-2">
          <span className="break-all">To {draft.to}</span> <Badge tone={tone}>{STATUS_TEXT[draft.status] ?? draft.status}</Badge>
          <Link className="font-normal text-indigo-700 hover:underline" to={`/jobs/${draft.job_id}`}>
            {draft.job_title} · {draft.company}
          </Link>
        </span>
      }
    >
      <div className="space-y-3">
        {draft.status === "failed" && <Alert tone="error">{failureHelp(draft)}</Alert>}
        <Field label="Subject">
          <TextInput value={subject} disabled={!editable} onChange={(e) => setSubject(e.target.value)} />
        </Field>
        <Field label="Body">
          <TextArea rows={12} value={body} disabled={!editable} onChange={(e) => setBody(e.target.value)} />
        </Field>
        <p className="text-xs text-slate-500">
          {draft.attachment_source === "master" ? (
            <>Attachment: <strong>base resume attached</strong> (your master resume, as uploaded: this job has no tailored resume), verified by checksum before sending.</>
          ) : (
            <>
              Attachment: tailored resume attached{" "}
              {draft.resume_version_id ? <Link className="text-indigo-700 hover:underline" to={`/resumes/${draft.resume_version_id}`}>your resume tailored for this job</Link> : "—"}{" "}
              ({draft.attachment_format.toUpperCase()}).
            </>
          )}
        </p>
        <div className="flex flex-wrap items-center gap-2">
          {editable && (
            <>
              <Button busy={save.isPending} onClick={() => save.mutate()} disabled={subject === draft.subject && body === draft.body}>
                Save
              </Button>
              <Button variant="primary" busy={send.isPending} onClick={() => window.confirm(`Send this email to ${draft.to}?`) && send.mutate()}>
                Send
              </Button>
            </>
          )}
          {draft.status === "failed" && (
            <Button variant="primary" busy={send.isPending} onClick={() => window.confirm(`Send this email to ${draft.to}?`) && send.mutate()}>
              Try again
            </Button>
          )}
          {draft.status === "scheduled" && (
            <>
              <span className="text-sm text-slate-600">Sends automatically {formatDate(draft.scheduled_for, true)}</span>
              <Button variant="primary" busy={send.isPending} onClick={() => window.confirm(`Send this email to ${draft.to}?`) && send.mutate()}>
                Send now
              </Button>
            </>
          )}
          {(editable || draft.status === "failed" || draft.status === "scheduled") && (
            <Button variant="danger" busy={cancel.isPending} onClick={() => window.confirm("Cancel this email? It will not be sent.") && cancel.mutate()}>
              Cancel
            </Button>
          )}
          {draft.status === "sent" && (
            <label className="flex items-center gap-2 text-sm">
              Follow-up
              <Select className="w-40" value={draft.follow_up_status} onChange={(e) => follow.mutate(e.target.value)}>
                <option value="none">Not needed</option>
                <option value="due">Due</option>
                <option value="done">Followed up</option>
                <option value="replied">They replied</option>
              </Select>
            </label>
          )}
        </div>
        {draft.status === "sending" && <Alert tone="warning">A send was interrupted. It is never resent automatically; check your sent mail.</Alert>}
        <ErrorText error={save.error || send.error || cancel.error || follow.error} />
        {draft.deliveries.length > 0 && (
          <div>
            <h3 className="mb-1 text-xs font-semibold uppercase text-slate-500">Send attempts</h3>
            <ul className="space-y-1 text-xs text-slate-600">
              {draft.deliveries.map((x, i) => (
                <li key={i}>
                  {formatDate(x.at, true)} · <Badge tone={x.status === "accepted" ? "green" : "red"}>{x.status === "accepted" ? "sent" : "failed"}</Badge> {x.error && `· ${x.error}`}
                  
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </Card>
  );
}

import { Check, ChevronDown, ClipboardList, ExternalLink, History } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";
import { useApplications, useUpdateApplication, type ApplicationPatch } from "../../api/hooks";
import type { Application, ApplicationStatus, Citizen } from "../../api/types";
import { Badge, Button, Card, cx, EmptyState, ErrorText, Field, formatDate, Input, Spinner, Textarea } from "../../components/ui";

const STEPS: ApplicationStatus[] = ["interested", "documents_ready", "submitted", "approved", "benefit_received"];

const tone = (status: ApplicationStatus) =>
  status === "approved" || status === "benefit_received" ? "green" : status === "rejected" ? "red" : status === "withdrawn" ? "stone" : "brand";

export function ApplicationsPanel({ citizen }: { citizen: Citizen }) {
  const { t } = useTranslation();
  const applications = useApplications(citizen.id);
  if (applications.isPending) return <Spinner />;
  if (applications.isError) return <ErrorText error={applications.error} />;
  if (applications.data.length === 0) {
    return (
      <EmptyState icon={ClipboardList} title={t("applications.noneTitle")}>
        {t("applications.none")}{" "}
        <Link to="../schemes" className="font-semibold text-brand-700 hover:underline">
          {t("tabs.schemes")}
        </Link>
      </EmptyState>
    );
  }
  return (
    <div className="space-y-5">
      {applications.data.map((application) => (
        <ApplicationCard key={application.id} citizenId={citizen.id} application={application} />
      ))}
    </div>
  );
}

function Stepper({ status }: { status: ApplicationStatus }) {
  const { t } = useTranslation();
  const current = STEPS.indexOf(status);
  if (current === -1) return null; // rejected / withdrawn are shown as a badge instead
  return (
    <ol className="flex items-start">
      {STEPS.map((step, i) => {
        const done = i < current;
        const active = i === current;
        return (
          <li key={step} className="relative flex flex-1 flex-col items-center text-center">
            {i > 0 && <span className={cx("absolute right-1/2 top-4 h-0.5 w-full -translate-y-1/2", i <= current ? "bg-brand-500" : "bg-stone-200")} aria-hidden />}
            <span
              className={cx(
                "relative z-10 flex h-8 w-8 items-center justify-center rounded-full text-xs font-bold ring-4 ring-white",
                done && "bg-brand-500 text-white",
                active && "bg-saffron-500 text-white shadow-md",
                !done && !active && "bg-stone-200 text-stone-500",
              )}
            >
              {done ? <Check className="h-4 w-4" aria-hidden /> : i + 1}
            </span>
            <span className={cx("mt-2 hidden text-xs sm:block", active ? "font-semibold text-brand-900" : "text-stone-500")}>{t(`status.${step}`)}</span>
          </li>
        );
      })}
    </ol>
  );
}

function ApplicationCard({ citizenId, application }: { citizenId: string; application: Application }) {
  const { t, i18n } = useTranslation();
  const update = useUpdateApplication(citizenId);
  const [reference, setReference] = useState(application.portal_reference ?? "");
  const [notes, setNotes] = useState(application.notes ?? "");
  const patch = (body: ApplicationPatch) => update.mutate({ id: application.id, patch: body });
  const docs = Object.entries(application.checklist);
  const ready = docs.filter(([, done]) => done).length;

  return (
    <Card className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-lg font-bold text-brand-950">{application.scheme_name}</h3>
          <p className="text-xs text-stone-500">{formatDate(application.updated_at, i18n.language)}</p>
        </div>
        <Badge tone={tone(application.status)}>{t(`status.${application.status}`)}</Badge>
      </div>

      <Stepper status={application.status} />

      <div className="grid gap-6 lg:grid-cols-2">
        <div>
          <div className="mb-3 flex items-center justify-between">
            <h4 className="text-sm font-semibold text-brand-950">{t("applications.checklist")}</h4>
            <span className="text-xs font-medium text-stone-500">
              {ready}/{docs.length}
            </span>
          </div>
          <div className="mb-3 h-1.5 overflow-hidden rounded-full bg-stone-100">
            <div className="h-full rounded-full bg-brand-500 transition-all" style={{ width: `${docs.length ? (ready / docs.length) * 100 : 0}%` }} />
          </div>
          <ul className="space-y-1.5">
            {docs.map(([doc, done]) => (
              <li key={doc}>
                <label className={cx("flex cursor-pointer items-start gap-3 rounded-xl px-3 py-2 text-sm transition", done ? "bg-brand-50" : "hover:bg-stone-50")}>
                  <input
                    type="checkbox"
                    className="mt-0.5 h-4 w-4 accent-brand-600"
                    checked={done}
                    onChange={(e) => patch({ checklist: { [doc]: e.target.checked } })}
                  />
                  <span className={done ? "text-stone-500 line-through" : "text-stone-800"}>{doc}</span>
                </label>
              </li>
            ))}
          </ul>
        </div>

        <div className="space-y-4">
          {application.next_statuses.length > 0 && (
            <div>
              <h4 className="mb-2 text-sm font-semibold text-brand-950">{t("applications.moveTo")}</h4>
              <div className="flex flex-wrap gap-2">
                {application.next_statuses.map((status) => (
                  <Button key={status} variant="secondary" className="px-3 py-2" disabled={update.isPending} onClick={() => patch({ status })}>
                    {t(`status.${status}`)}
                  </Button>
                ))}
              </div>
            </div>
          )}
          <Field label={t("applications.reference")} hint={t("applications.referenceHint")}>
            <Input value={reference} maxLength={100} onChange={(e) => setReference(e.target.value)} />
          </Field>
          <Field label={t("applications.notes")}>
            <Textarea rows={2} value={notes} maxLength={2000} onChange={(e) => setNotes(e.target.value)} />
          </Field>
          <div className="flex flex-wrap items-center gap-3">
            <Button variant="secondary" disabled={update.isPending} onClick={() => patch({ portal_reference: reference, notes })}>
              {t("common.save")}
            </Button>
            {application.apply_url && (
              <a
                href={application.apply_url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1.5 text-sm font-semibold text-brand-700 hover:underline"
              >
                {t("applications.openPortal")}
                <ExternalLink className="h-4 w-4" aria-hidden />
              </a>
            )}
          </div>
        </div>
      </div>
      <ErrorText error={update.error} />

      <details className="group text-sm">
        <summary className="flex cursor-pointer list-none items-center gap-2 font-semibold text-stone-600">
          <History className="h-4 w-4" aria-hidden />
          {t("applications.history")}
          <ChevronDown className="h-4 w-4 transition group-open:rotate-180" aria-hidden />
        </summary>
        <ol className="mt-3 space-y-2 border-l-2 border-brand-100 pl-4">
          {application.events.map((event, i) => (
            <li key={i} className="text-stone-600">
              <span className="font-medium text-stone-800">{t(`status.${event.to_status}`)}</span> · {formatDate(event.created_at, i18n.language)}
              {event.note && <span className="block text-stone-500">{event.note}</span>}
            </li>
          ))}
        </ol>
      </details>
    </Card>
  );
}

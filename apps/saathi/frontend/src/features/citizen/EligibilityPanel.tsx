import { AlertTriangle, CheckCircle2, ChevronDown, CircleHelp, ExternalLink, FileText, Info, Landmark, ListChecks, MapPin, Plus, XCircle } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";
import { useApplications, useEligibility, useProfileFields, useScheme, useStartApplication } from "../../api/hooks";
import type { Citizen, Match } from "../../api/types";
import { schemeIcon } from "../../components/schemeIcon";
import { Badge, Button, cx, EmptyState, ErrorText, Notice, Spinner } from "../../components/ui";
import { fieldLabel, optionLabel } from "../../i18n/fields";

export function EligibilityPanel({ citizen }: { citizen: Citizen }) {
  const { t } = useTranslation();
  const matches = useEligibility(citizen.id);
  const applications = useApplications(citizen.id);
  const start = useStartApplication(citizen.id);

  if (matches.isPending) return <Spinner />;
  if (matches.isError) return <ErrorText error={matches.error} />;

  const tracked = new Set(applications.data?.map((a) => a.scheme_id));
  const eligible = matches.data.filter((m) => m.status === "eligible");
  const maybe = matches.data.filter((m) => m.status === "needs_info");
  const no = matches.data.filter((m) => m.status === "not_eligible");

  return (
    <div className="space-y-8">
      <div className="grid gap-3 sm:grid-cols-3">
        <Counter icon={CheckCircle2} tone="text-emerald-600 bg-emerald-50" value={eligible.length} label={t("schemes.eligible")} />
        <Counter icon={CircleHelp} tone="text-saffron-600 bg-saffron-50" value={maybe.length} label={t("schemes.needsInfoShort")} />
        <Counter icon={XCircle} tone="text-stone-500 bg-stone-100" value={no.length} label={t("schemes.notEligible")} />
      </div>

      <Notice tone="amber" icon={Info}>
        {t("schemes.verifyNote")}
      </Notice>
      <ErrorText error={start.error} />

      {eligible.length === 0 && maybe.length === 0 && (
        <EmptyState icon={ListChecks} title={t("schemes.noneYetTitle")}>
          {t("schemes.noneYet")}{" "}
          <Link to="../profile" className="font-semibold text-brand-700 hover:underline">
            {t("tabs.profile")}
          </Link>
        </EmptyState>
      )}

      {eligible.length > 0 && (
        <Section title={t("schemes.eligible")} count={eligible.length}>
          {eligible.map((m) => (
            <MatchCard key={m.scheme_id} match={m}>
              {tracked.has(m.scheme_id) ? (
                <Badge tone="brand" icon={ListChecks}>
                  {t("schemes.tracking")}
                </Badge>
              ) : (
                <Button
                  variant="accent"
                  className="px-3 py-2"
                  onClick={() => start.mutate(m.scheme_id)}
                  loading={start.isPending && start.variables === m.scheme_id}
                >
                  <Plus className="h-4 w-4" aria-hidden />
                  {t("schemes.track")}
                </Button>
              )}
            </MatchCard>
          ))}
        </Section>
      )}

      {maybe.length > 0 && (
        <Section title={t("schemes.needsInfo")} count={maybe.length}>
          {maybe.map((m) => (
            <MatchCard key={m.scheme_id} match={m} />
          ))}
        </Section>
      )}

      {no.length > 0 && (
        <details className="group rounded-2xl bg-white p-4 shadow-card ring-1 ring-stone-200/70">
          <summary className="flex cursor-pointer list-none items-center justify-between text-sm font-semibold text-stone-600">
            {t("schemes.notEligible")} ({no.length})
            <ChevronDown className="h-4 w-4 transition group-open:rotate-180" aria-hidden />
          </summary>
          <ul className="mt-3 space-y-2">
            {no.map((m) => (
              <li key={m.scheme_id} className="rounded-xl bg-stone-50 px-3 py-2 text-sm">
                <span className="font-medium text-stone-800">{m.scheme_name}</span>
                <span className="block text-stone-500">{m.failed_reasons.join(" · ")}</span>
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

function Counter({ icon: Icon, tone, value, label }: { icon: LucideIcon; tone: string; value: number; label: string }) {
  return (
    <div className="flex items-center gap-4 rounded-2xl bg-white p-4 shadow-card ring-1 ring-stone-200/70">
      <span className={cx("flex h-12 w-12 items-center justify-center rounded-xl", tone)}>
        <Icon className="h-6 w-6" aria-hidden />
      </span>
      <div>
        <p className="text-2xl font-bold text-brand-950">{value}</p>
        <p className="text-xs font-medium text-stone-500">{label}</p>
      </div>
    </div>
  );
}

function Section({ title, count, children }: { title: string; count: number; children: ReactNode }) {
  return (
    <section className="space-y-3">
      <h2 className="flex items-center gap-2 text-lg font-bold text-brand-950">
        {title}
        <span className="rounded-full bg-brand-100 px-2 py-0.5 text-xs font-semibold text-brand-700">{count}</span>
      </h2>
      <div className="grid gap-4 lg:grid-cols-2">{children}</div>
    </section>
  );
}

function MatchCard({ match, children }: { match: Match; children?: ReactNode }) {
  const { t, i18n } = useTranslation();
  const fields = useProfileFields();
  const [open, setOpen] = useState(false);
  const { icon: Icon, tint } = schemeIcon(match.tags);
  const missing = match.missing_fields
    .map((name) => fieldLabel(i18n.language, name, fields.data?.find((f) => f.name === name)?.label ?? name))
    .join(", ");

  return (
    <article className="flex flex-col rounded-2xl bg-white p-5 shadow-card ring-1 ring-stone-200/70 transition hover:shadow-lift">
      <div className="flex items-start gap-4">
        <span className={cx("flex h-12 w-12 shrink-0 items-center justify-center rounded-xl", tint)}>
          <Icon className="h-6 w-6" aria-hidden />
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="font-semibold leading-snug text-brand-950">{match.scheme_name}</h3>
          <div className="mt-1">
            {match.level === "state" && match.state ? (
              <Badge tone="amber" icon={MapPin}>
                {t("schemes.stateScheme", { state: optionLabel(i18n.language, match.state) })}
              </Badge>
            ) : (
              <Badge tone="stone" icon={Landmark}>
                {t("schemes.centralScheme")}
              </Badge>
            )}
          </div>
          <p className="mt-1 text-sm leading-relaxed text-stone-600">{match.benefits}</p>
        </div>
      </div>
      {missing && (
        <p className="mt-3 flex items-start gap-2 rounded-xl bg-saffron-50 px-3 py-2 text-xs text-saffron-600">
          <CircleHelp className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
          {t("schemes.missing", { fields: missing })}
        </p>
      )}
      <div className="mt-4 flex flex-wrap items-center justify-between gap-2 border-t border-stone-100 pt-3">
        <button
          type="button"
          className="flex items-center gap-1 text-sm font-semibold text-brand-700 hover:text-brand-900"
          onClick={() => setOpen(!open)}
          aria-expanded={open}
        >
          <FileText className="h-4 w-4" aria-hidden />
          {open ? t("schemes.hide") : t("schemes.details")}
          <ChevronDown className={cx("h-4 w-4 transition", open && "rotate-180")} aria-hidden />
        </button>
        {children}
      </div>
      {open && <SchemeDetails schemeId={match.scheme_id} />}
    </article>
  );
}

function SchemeDetails({ schemeId }: { schemeId: string }) {
  const { t } = useTranslation();
  const scheme = useScheme(schemeId);
  if (scheme.isPending) return <Spinner />;
  if (scheme.isError) return <ErrorText error={scheme.error} />;
  const s = scheme.data;
  return (
    <div className="mt-4 animate-fade-up space-y-4 text-sm">
      {s.status !== "verified" && (
        <Badge tone="amber" icon={AlertTriangle}>
          {t("schemes.draft")}
        </Badge>
      )}
      {s.notes.length > 0 && (
        <div className="rounded-xl bg-saffron-50 p-3">
          <h4 className="font-semibold text-saffron-600">{t("schemes.conditions")}</h4>
          <ul className="mt-1 list-disc space-y-1 pl-5 text-stone-700">
            {s.notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        </div>
      )}
      <div>
        <h4 className="font-semibold text-brand-950">{t("schemes.documents")}</h4>
        <ul className="mt-2 space-y-1.5">
          {s.documents.map((d) => (
            <li key={d} className="flex items-start gap-2 text-stone-700">
              <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-brand-500" aria-hidden />
              {d}
            </li>
          ))}
        </ul>
      </div>
      <div>
        <h4 className="font-semibold text-brand-950">{t("schemes.howToApply")}</h4>
        <p className="mt-1 leading-relaxed text-stone-700">{s.how_to_apply}</p>
      </div>
      <a
        href={s.apply_url ?? s.source_url}
        target="_blank"
        rel="noopener noreferrer"
        className="inline-flex items-center gap-1.5 font-semibold text-brand-700 hover:underline"
      >
        {t("schemes.official")}
        <ExternalLink className="h-4 w-4" aria-hidden />
      </a>
    </div>
  );
}

import { ChevronRight, Search, UserPlus, UsersRound } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate } from "react-router";
import { useCitizens, useCreateCitizen } from "../../api/hooks";
import { Badge, Button, Card, EmptyState, ErrorText, Field, formatDate, Initials, Input, PageHeader, Spinner } from "../../components/ui";

export function CitizensPage() {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const citizens = useCitizens(query.trim());
  const create = useCreateCitizen();
  const [name, setName] = useState("");
  const [language, setLanguage] = useState("");

  const submit = (event: FormEvent) => {
    event.preventDefault();
    create.mutate({ display_name: name, language: language || undefined }, { onSuccess: (c) => navigate(`/citizens/${c.id}/chat`) });
  };

  return (
    <div className="animate-fade-up space-y-6">
      <PageHeader icon={UsersRound} title={t("citizens.title")} subtitle={t("citizens.subtitle")} />

      <div className="grid gap-6 lg:grid-cols-[1fr_340px]">
        <div className="space-y-4">
          <div className="relative">
            <Search className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-stone-400" aria-hidden />
            <Input
              type="search"
              className="pl-10"
              placeholder={t("common.search")}
              aria-label={t("common.search")}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </div>
          {citizens.isPending ? (
            <Spinner />
          ) : citizens.isError ? (
            <ErrorText error={citizens.error} />
          ) : citizens.data.length === 0 ? (
            <EmptyState icon={UsersRound} title={t("citizens.empty")}>
              {t("citizens.emptyHint")}
            </EmptyState>
          ) : (
            <ul className="divide-y divide-stone-100 overflow-hidden rounded-2xl bg-white shadow-card ring-1 ring-stone-200/70">
              {citizens.data.map((c) => (
                <li key={c.id}>
                  <Link to={`/citizens/${c.id}/chat`} className="flex items-center gap-4 px-4 py-3.5 transition hover:bg-brand-50/50">
                    <Initials name={c.display_name} />
                    <div className="min-w-0 flex-1">
                      <p className="truncate font-semibold text-stone-900">{c.display_name}</p>
                      <p className="truncate text-xs text-stone-500">
                        {t("citizens.updated")}: {formatDate(c.updated_at, i18n.language)}
                        {c.language && ` · ${c.language}`}
                      </p>
                    </div>
                    {!c.consent_at && <Badge tone="amber">{t("citizens.needsConsent")}</Badge>}
                    <ChevronRight className="h-5 w-5 text-stone-400" aria-hidden />
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </div>

        <Card className="h-fit">
          <form onSubmit={submit} className="space-y-4">
            <h2 className="flex items-center gap-2 font-bold text-brand-950">
              <UserPlus className="h-5 w-5 text-brand-600" aria-hidden />
              {t("citizens.add")}
            </h2>
            <Field label={t("citizens.name")}>
              <Input required maxLength={120} value={name} onChange={(e) => setName(e.target.value)} />
            </Field>
            <Field label={t("citizens.language")}>
              <Input maxLength={80} value={language} onChange={(e) => setLanguage(e.target.value)} placeholder="Hindi, Tamil…" />
            </Field>
            <ErrorText error={create.error} />
            <Button type="submit" className="w-full" loading={create.isPending}>
              {t("citizens.add")}
            </Button>
          </form>
        </Card>
      </div>
    </div>
  );
}

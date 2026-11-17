import { ArrowLeft } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useParams } from "react-router";
import { useAdminScheme, useSaveScheme, useSchemeAction, useSchemeRevisions } from "../../api/hooks";
import type { Rule, SchemeInput } from "../../api/types";
import { Badge, Button, Card, ErrorText, Field, formatDate, Input, Notice, Select, Spinner, Textarea } from "../../components/ui";
import { statusTone } from "./SchemesPage";

interface FormState {
  id: string;
  name: string;
  level: "central" | "state";
  state: string;
  ministry: string;
  tags: string;
  summary: string;
  benefits: string;
  eligibility: string;
  documents: string;
  notes: string;
  how_to_apply: string;
  apply_url: string;
  source_url: string;
}

const EMPTY: FormState = {
  id: "", name: "", level: "central", state: "", ministry: "", tags: "", summary: "", benefits: "",
  eligibility: "[]", documents: "", notes: "", how_to_apply: "", apply_url: "", source_url: "",
};

function toForm(s: SchemeInput): FormState {
  return {
    ...s,
    state: s.state ?? "",
    tags: s.tags.join(", "),
    eligibility: JSON.stringify(s.eligibility, null, 2),
    documents: s.documents.join("\n"),
    notes: (s.notes ?? []).join("\n"),
    apply_url: s.apply_url ?? "",
  };
}

function toInput(f: FormState): SchemeInput {
  let eligibility: Rule[];
  try {
    eligibility = JSON.parse(f.eligibility);
  } catch {
    throw new Error("Eligibility rules are not valid JSON");
  }
  return {
    id: f.id.trim(),
    name: f.name.trim(),
    level: f.level,
    state: f.level === "state" ? f.state.trim() || null : null,
    ministry: f.ministry.trim(),
    tags: f.tags.split(",").map((s) => s.trim()).filter(Boolean),
    summary: f.summary.trim(),
    benefits: f.benefits.trim(),
    eligibility,
    documents: f.documents.split("\n").map((s) => s.trim()).filter(Boolean),
    notes: f.notes.split("\n").map((s) => s.trim()).filter(Boolean),
    how_to_apply: f.how_to_apply.trim(),
    apply_url: f.apply_url.trim() || null,
    source_url: f.source_url.trim(),
  };
}

export function SchemeEditor() {
  const { schemeId } = useParams();
  const isNew = !schemeId;
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const scheme = useAdminScheme(schemeId);
  const revisions = useSchemeRevisions(schemeId);
  const save = useSaveScheme(!isNew);
  const action = useSchemeAction();
  const [form, setForm] = useState<FormState>(EMPTY);
  const [localError, setLocalError] = useState<unknown>(null);

  useEffect(() => {
    if (scheme.data) setForm(toForm(scheme.data));
  }, [scheme.data]);

  if (!isNew && scheme.isPending) return <Spinner />;
  if (!isNew && scheme.isError) return <ErrorText error={scheme.error} />;
  const current = scheme.data;

  const set = (key: keyof FormState) => (e: { target: { value: string } }) => setForm({ ...form, [key]: e.target.value });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setLocalError(null);
    try {
      save.mutate(toInput(form), { onSuccess: (saved) => isNew && navigate(`/admin/schemes/${saved.id}`, { replace: true }) });
    } catch (error) {
      setLocalError(error);
    }
  };

  return (
    <div className="animate-fade-up space-y-5">
      <Link to="/admin/schemes" className="inline-flex items-center gap-1.5 text-sm font-semibold text-brand-700 hover:underline">
        <ArrowLeft className="h-4 w-4" aria-hidden />
        {t("common.back")}
      </Link>
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-2xl font-bold tracking-tight text-brand-950">{isNew ? t("admin.newScheme") : scheme.data?.name}</h1>
        {scheme.data && (
          <>
            <Badge tone={statusTone(scheme.data.status)}>{t(`status.${scheme.data.status}`)}</Badge>
            <span className="text-sm text-stone-500">
              {t("admin.version")} {scheme.data.version}
            </span>
          </>
        )}
      </div>
      {!isNew && <Notice tone="amber">{t("admin.editWarning")}</Notice>}

      <Card>
        <form onSubmit={submit} className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="ID (slug)">
              <Input required pattern="[a-z0-9-]+" value={form.id} onChange={set("id")} disabled={!isNew} />
            </Field>
            <Field label="Name">
              <Input required value={form.name} onChange={set("name")} />
            </Field>
            <Field label="Level">
              <Select value={form.level} onChange={set("level")}>
                <option value="central">central</option>
                <option value="state">state</option>
              </Select>
            </Field>
            {form.level === "state" && (
              <Field label="State (e.g. uttar_pradesh)">
                <Input required value={form.state} onChange={set("state")} />
              </Field>
            )}
            <Field label="Ministry / department">
              <Input required value={form.ministry} onChange={set("ministry")} />
            </Field>
            <Field label="Tags (comma separated)">
              <Input value={form.tags} onChange={set("tags")} />
            </Field>
            <Field label="Official source URL (checked when verifying)">
              <Input required type="url" value={form.source_url} onChange={set("source_url")} />
            </Field>
            <Field label="Apply URL">
              <Input type="url" value={form.apply_url} onChange={set("apply_url")} />
            </Field>
          </div>
          <Field label="Summary">
            <Textarea required rows={2} value={form.summary} onChange={set("summary")} />
          </Field>
          <Field label="Benefits">
            <Textarea required rows={2} value={form.benefits} onChange={set("benefits")} />
          </Field>
          <Field label="Documents (one per line)">
            <Textarea rows={5} value={form.documents} onChange={set("documents")} />
          </Field>
          <Field label="Important conditions the rules cannot check (one per line)">
            <Textarea rows={4} value={form.notes} onChange={set("notes")} />
          </Field>
          <Field label="How to apply">
            <Textarea required rows={3} value={form.how_to_apply} onChange={set("how_to_apply")} />
          </Field>
          <Field label="Eligibility rules" hint={t("admin.rulesHelp")}>
            <Textarea rows={14} spellCheck={false} className="font-mono" value={form.eligibility} onChange={set("eligibility")} />
          </Field>
          <ErrorText error={localError ?? save.error} />
          <div className="flex flex-wrap gap-2">
            <Button type="submit" disabled={save.isPending}>
              {t("common.save")}
            </Button>
            {current && current.status !== "verified" && (
              <Button type="button" variant="secondary" disabled={action.isPending} onClick={() => action.mutate({ id: current.id, action: "verify" })}>
                {t("admin.verify")}
              </Button>
            )}
            {current && current.status !== "archived" && (
              <Button type="button" variant="danger" disabled={action.isPending} onClick={() => window.confirm(t("common.confirm")) && action.mutate({ id: current.id, action: "archive" })}>
                {t("admin.archive")}
              </Button>
            )}
          </div>
          <ErrorText error={action.error} />
        </form>
      </Card>

      {revisions.data && revisions.data.length > 0 && (
        <Card>
          <h2 className="mb-2 font-semibold">{t("admin.revisions")}</h2>
          <ul className="space-y-1 text-sm">
            {revisions.data.map((r) => (
              <li key={r.version} className="flex items-center justify-between gap-2">
                <span>
                  v{r.version} · {formatDate(r.changed_at, i18n.language)}
                </span>
                <Button variant="ghost" onClick={() => setForm(toForm(r.data))}>
                  {t("admin.edit")}
                </Button>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}

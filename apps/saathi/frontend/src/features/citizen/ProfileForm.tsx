import { Briefcase, CheckCircle2, Home, MapPin, Plus, Trash2, UserRound, Users } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { useProfileFields, useUpdateDetails, useUpdateProfile } from "../../api/hooks";
import type { Citizen, FamilyMember, Profile, ProfileField, ProfileValue, Relation } from "../../api/types";
import { AddressFields, PersonalFields, type DetailsValue } from "../../components/DetailsFields";
import { Button, Card, cx, ErrorText, Field, Input, Select, Spinner } from "../../components/ui";
import { fieldLabel, optionLabel } from "../../i18n/fields";

type Value = ProfileValue | undefined;

const scalar = (value: Profile[string]): Value => (Array.isArray(value) ? undefined : value);

const MAX_FAMILY = 12;
const RELATIONS: Relation[] = ["spouse", "son", "daughter", "father", "mother", "other"];
// Facts asked about each family member; household facts (state, income, ...) are shared.
const MEMBER_FIELDS: ProfileField[] = [
  { name: "gender", label: "Gender", question: "", type: "enum", options: ["male", "female", "transgender"] },
  { name: "is_studying_post_matric", label: "Studying in class 11 or above", question: "", type: "bool", options: [] },
  { name: "is_widow", label: "Is a widow", question: "", type: "bool", options: [] },
  { name: "is_pregnant", label: "Pregnant now", question: "", type: "bool", options: [] },
  { name: "is_pregnant_or_lactating", label: "Pregnant or breastfeeding", question: "", type: "bool", options: [] },
  { name: "current_class", label: "School class now (1 to 12)", question: "", type: "int", options: [] },
  { name: "is_government_employee", label: "Government employee or pensioner", question: "", type: "bool", options: [] },
  { name: "has_paid_income_tax", label: "Has ever paid income tax", question: "", type: "bool", options: [] },
  { name: "disability_percent", label: "Disability percentage", question: "", type: "int", options: [] },
];

// Set from the personal details card above, not asked again here.
const FROM_DETAILS = new Set(["state", "district", "gender", "residence"]);

const GROUPS: { id: string; icon: LucideIcon; fields: string[] }[] = [
  {
    id: "about",
    icon: UserRound,
    fields: [
      "age", "social_category", "current_class", "is_widow", "is_pregnant", "is_pregnant_or_lactating", "has_disability",
      "disability_percent",
    ],
  },
  {
    id: "work",
    icon: Briefcase,
    fields: [
      "occupation", "annual_family_income", "is_income_tax_payer", "has_paid_income_tax", "is_government_employee", "has_epf_esic_or_nps",
      "owns_cultivable_land", "land_holding_hectares", "plans_new_business",
    ],
  },
];

export function ProfileForm({ citizen }: { citizen: Citizen }) {
  const { t, i18n } = useTranslation();
  const fields = useProfileFields();
  const update = useUpdateProfile(citizen.id);
  const [values, setValues] = useState<Profile>(citizen.profile);

  if (fields.isPending) return <Spinner />;
  if (fields.isError) return <ErrorText error={fields.error} />;

  const grouped = new Set([...GROUPS.flatMap((g) => g.fields), ...FROM_DETAILS]);
  const groups = [
    ...GROUPS.map((g) => ({ ...g, items: g.fields.map((name) => fields.data.find((f) => f.name === name)).filter((f): f is ProfileField => !!f) })),
    { id: "household", icon: Home, fields: [], items: fields.data.filter((f) => !grouped.has(f.name)) },
  ];

  const set = (name: string, value: Value) =>
    setValues((current) => {
      const next = { ...current };
      if (value === undefined || value === "") delete next[name];
      else next[name] = value;
      return next;
    });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    // Fields owned by the details card always come from the latest saved record.
    const latest: Profile = { ...values };
    for (const name of FROM_DETAILS) {
      if (citizen.profile[name] !== undefined) latest[name] = citizen.profile[name];
      else delete latest[name];
    }
    if (citizen.date_of_birth && citizen.profile.age !== undefined) latest.age = citizen.profile.age;
    update.mutate(latest);
  };

  return (
    <div className="space-y-8">
    <DetailsCard citizen={citizen} />
    <form onSubmit={submit} className="space-y-5 pb-4">
      <div className="pt-2">
        <h2 className="text-lg font-bold text-brand-950">{t("profile.title")}</h2>
        <p className="text-sm text-stone-600">{t("profile.hint")}</p>
      </div>
      {groups.map(({ id, icon: Icon, items }) => (
        <Card key={id}>
          <h3 className="mb-5 flex items-center gap-2 font-semibold text-brand-900">
            <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand-50 text-brand-600">
              <Icon className="h-4 w-4" aria-hidden />
            </span>
            {t(`profile.group.${id}`)}
          </h3>
          <div className="grid gap-5 sm:grid-cols-2">
            {items.map((field) =>
              field.name === "age" && citizen.date_of_birth ? (
                <Field key={field.name} label={fieldLabel(i18n.language, field.name, field.label)} hint={t("details.ageFromDob")}>
                  <Input value={String(citizen.profile.age ?? "")} disabled />
                </Field>
              ) : (
                <Field key={field.name} label={fieldLabel(i18n.language, field.name, field.label)} group={field.type === "bool"}>
                  <FieldInput field={field} value={scalar(values[field.name])} onChange={(v) => set(field.name, v)} />
                </Field>
              ),
            )}
          </div>
        </Card>
      ))}
      <FamilyCard
        members={values.family_members ?? []}
        onChange={(members) => setValues((current) => ({ ...current, family_members: members }))}
      />
      <div className="sticky bottom-4 z-10 flex flex-wrap items-center gap-3 rounded-2xl bg-white/90 p-3 shadow-lift ring-1 ring-stone-200 backdrop-blur">
        <Button type="submit" loading={update.isPending} className="px-6">
          {t("profile.save")}
        </Button>
        {update.isSuccess && (
          <span className="flex items-center gap-1.5 text-sm font-medium text-emerald-700">
            <CheckCircle2 className="h-4 w-4" aria-hidden />
            {t("common.saved")}
          </span>
        )}
        <div className="w-full">
          <ErrorText error={update.error} />
        </div>
      </div>
    </form>
    </div>
  );
}

function DetailsCard({ citizen }: { citizen: Citizen }) {
  const { t } = useTranslation();
  const update = useUpdateDetails(citizen.id);
  const p = citizen.profile;
  const [details, setDetails] = useState<DetailsValue>({
    display_name: citizen.display_name,
    date_of_birth: citizen.date_of_birth,
    contact_email: citizen.contact_email,
    pincode: citizen.pincode,
    locality: citizen.locality,
    address_line: citizen.address_line,
    gender: (p.gender as string) ?? null,
    state: (p.state as string) ?? null,
    district: p.district ? optionLabel("en", String(p.district)) : null,
    residence: (p.residence as string) ?? null,
  });
  const submit = (event: FormEvent) => {
    event.preventDefault();
    update.mutate(details);
  };
  return (
    <Card>
      <form onSubmit={submit} className="space-y-6">
        <h2 className="flex items-center gap-2 text-lg font-bold text-brand-950">
          <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand-50 text-brand-600">
            <MapPin className="h-4 w-4" aria-hidden />
          </span>
          {t("details.title")}
        </h2>
        <PersonalFields value={details} onChange={setDetails} />
        <div className="border-t border-stone-100 pt-6">
          <AddressFields value={details} onChange={setDetails} />
        </div>
        <ErrorText error={update.error} />
        <div className="flex items-center gap-3">
          <Button type="submit" loading={update.isPending}>
            {t("details.save")}
          </Button>
          {update.isSuccess && (
            <span className="flex items-center gap-1.5 text-sm font-medium text-emerald-700">
              <CheckCircle2 className="h-4 w-4" aria-hidden />
              {t("common.saved")}
            </span>
          )}
        </div>
      </form>
    </Card>
  );
}

function FamilyCard({ members, onChange }: { members: FamilyMember[]; onChange: (members: FamilyMember[]) => void }) {
  const { t, i18n } = useTranslation();
  const update = (index: number, change: Partial<FamilyMember>) =>
    onChange(
      members.map((member, i) => {
        if (i !== index) return member;
        const next: FamilyMember = { ...member, ...change };
        for (const key of Object.keys(change) as (keyof FamilyMember)[]) {
          if (next[key] === undefined) delete next[key];
        }
        return next;
      }),
    );

  return (
    <Card>
      <h3 className="mb-1 flex items-center gap-2 font-semibold text-brand-900">
        <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand-50 text-brand-600">
          <Users className="h-4 w-4" aria-hidden />
        </span>
        {t("family.title")}
      </h3>
      <p className="mb-5 text-sm text-stone-600">{t("family.hint")}</p>
      {members.length === 0 && <p className="mb-4 text-sm text-stone-500">{t("family.empty")}</p>}
      <ul className="space-y-4">
        {members.map((member, index) => (
          <li key={index} className="rounded-xl bg-stone-50 p-4 ring-1 ring-stone-200/70">
            <div className="grid gap-4 sm:grid-cols-[1fr_8rem_auto] sm:items-end">
              <Field label={t("family.relation")}>
                <Select value={member.relation} onChange={(e) => update(index, { relation: e.target.value as Relation })}>
                  {RELATIONS.map((relation) => (
                    <option key={relation} value={relation}>
                      {t(`family.relations.${relation}`)}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label={t("family.age")}>
                <Input
                  type="number"
                  min={0}
                  max={120}
                  inputMode="numeric"
                  value={member.age ?? ""}
                  onChange={(e) => update(index, { age: e.target.value === "" ? undefined : Number(e.target.value) })}
                />
              </Field>
              <Button
                type="button"
                variant="ghost"
                className="justify-self-start px-3 py-2"
                onClick={() => onChange(members.filter((_, i) => i !== index))}
              >
                <Trash2 className="h-4 w-4" aria-hidden />
                {t("family.remove")}
              </Button>
            </div>
            <details className="mt-3">
              <summary className="cursor-pointer text-sm font-semibold text-brand-700">{t("family.more")}</summary>
              <div className="mt-4 grid gap-5 sm:grid-cols-2">
                {MEMBER_FIELDS.map((field) => (
                  <Field key={field.name} label={fieldLabel(i18n.language, field.name, field.label)} group={field.type === "bool"}>
                    <FieldInput
                      field={field}
                      value={member[field.name as keyof FamilyMember] as Value}
                      onChange={(v) => update(index, { [field.name]: v })}
                    />
                  </Field>
                ))}
              </div>
            </details>
          </li>
        ))}
      </ul>
      {members.length < MAX_FAMILY && (
        <Button type="button" variant="secondary" className="mt-4" onClick={() => onChange([...members, { relation: "spouse" }])}>
          <Plus className="h-4 w-4" aria-hidden />
          {t("family.add")}
        </Button>
      )}
    </Card>
  );
}

function FieldInput({ field, value, onChange }: { field: ProfileField; value: Value; onChange: (value: Value) => void }) {
  const { t, i18n } = useTranslation();
  if (field.type === "text") {
    return <Input maxLength={80} value={value === undefined ? "" : String(value)} onChange={(e) => onChange(e.target.value || undefined)} />;
  }
  if (field.type === "int" || field.type === "number") {
    return (
      <Input
        type="number"
        min={0}
        step={field.type === "number" ? "0.01" : "1"}
        inputMode={field.type === "number" ? "decimal" : "numeric"}
        value={value === undefined ? "" : String(value)}
        onChange={(e) => onChange(e.target.value === "" ? undefined : Number(e.target.value))}
      />
    );
  }
  if (field.type === "bool") {
    const options: { label: string; value: Value }[] = [
      { label: t("common.yes"), value: true },
      { label: t("common.no"), value: false },
      { label: t("profile.unknown"), value: undefined },
    ];
    return (
      <div role="radiogroup" className="grid grid-cols-3 gap-1 rounded-xl bg-stone-100 p-1">
        {options.map((option) => (
          <button
            key={option.label}
            type="button"
            role="radio"
            aria-checked={value === option.value}
            onClick={() => onChange(option.value)}
            className={cx(
              "rounded-lg px-2 py-2 text-sm font-medium transition",
              value === option.value
                ? option.value === undefined
                  ? "bg-white text-stone-700 shadow-sm"
                  : "bg-brand-700 text-white shadow-sm"
                : "text-stone-500 hover:text-stone-800",
            )}
          >
            {option.label}
          </button>
        ))}
      </div>
    );
  }
  return (
    <Select value={value === undefined ? "" : String(value)} onChange={(e) => onChange(e.target.value || undefined)}>
      <option value="">{t("profile.unknown")}</option>
      {field.options.map((option) => (
        <option key={option} value={option}>
          {optionLabel(i18n.language, option)}
        </option>
      ))}
    </Select>
  );
}

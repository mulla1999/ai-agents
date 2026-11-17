import { Briefcase, CheckCircle2, Home, MapPin, UserRound } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { useProfileFields, useUpdateDetails, useUpdateProfile } from "../../api/hooks";
import type { Citizen, Profile, ProfileField } from "../../api/types";
import { AddressFields, PersonalFields, type DetailsValue } from "../../components/DetailsFields";
import { Button, Card, cx, ErrorText, Field, Input, Select, Spinner } from "../../components/ui";
import { fieldLabel, optionLabel } from "../../i18n/fields";

type Value = string | number | boolean | undefined;

// Set from the personal details card above, not asked again here.
const FROM_DETAILS = new Set(["state", "district", "gender", "residence"]);

const GROUPS: { id: string; icon: LucideIcon; fields: string[] }[] = [
  { id: "about", icon: UserRound, fields: ["age", "social_category"] },
  {
    id: "work",
    icon: Briefcase,
    fields: ["occupation", "annual_family_income", "is_income_tax_payer", "is_government_employee", "owns_cultivable_land", "plans_new_business"],
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
                  <FieldInput field={field} value={values[field.name]} onChange={(v) => set(field.name, v)} />
                </Field>
              ),
            )}
          </div>
        </Card>
      ))}
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

function FieldInput({ field, value, onChange }: { field: ProfileField; value: Value; onChange: (value: Value) => void }) {
  const { t, i18n } = useTranslation();
  if (field.type === "text") {
    return <Input maxLength={80} value={value === undefined ? "" : String(value)} onChange={(e) => onChange(e.target.value || undefined)} />;
  }
  if (field.type === "int") {
    return (
      <Input
        type="number"
        min={0}
        inputMode="numeric"
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

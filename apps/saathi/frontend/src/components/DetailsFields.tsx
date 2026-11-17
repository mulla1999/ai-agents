import { useTranslation } from "react-i18next";
import { useProfileFields } from "../api/hooks";
import type { CitizenDetails } from "../api/types";
import { optionLabel } from "../i18n/fields";
import { cx, Field, Input, Select } from "./ui";

export type DetailsValue = CitizenDetails;
type Props = { value: DetailsValue; onChange: (value: DetailsValue) => void };

export function Segmented<T extends string>({
  options,
  value,
  onChange,
  label,
}: {
  options: { value: T; label: string }[];
  value: T | null | undefined;
  onChange: (value: T | null) => void;
  label: string;
}) {
  return (
    <div role="radiogroup" aria-label={label} className={cx("grid gap-1 rounded-xl bg-stone-100 p-1", options.length === 2 ? "grid-cols-2" : "grid-cols-3")}>
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          role="radio"
          aria-checked={value === option.value}
          onClick={() => onChange(value === option.value ? null : option.value)}
          className={cx(
            "rounded-lg px-2 py-2 text-sm font-medium transition",
            value === option.value ? "bg-brand-700 text-white shadow-sm" : "text-stone-600 hover:text-stone-900",
          )}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

const today = () => new Date().toISOString().slice(0, 10);

/** Name, date of birth, gender, contact email. */
export function PersonalFields({ value, onChange, nameRequired = true }: Props & { nameRequired?: boolean }) {
  const { t, i18n } = useTranslation();
  const set = (patch: Partial<DetailsValue>) => onChange({ ...value, ...patch });
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <div className="sm:col-span-2">
        <Field label={t("details.name")}>
          <Input required={nameRequired} maxLength={120} autoComplete="name" value={value.display_name} onChange={(e) => set({ display_name: e.target.value })} />
        </Field>
      </div>
      <Field label={t("details.dob")} hint={t("details.dobHint")}>
        <Input type="date" max={today()} min="1900-01-01" value={value.date_of_birth ?? ""} onChange={(e) => set({ date_of_birth: e.target.value || null })} />
      </Field>
      <div className="sm:col-span-2">
      <Field label={t("details.gender")} group>
        <Segmented
          label={t("details.gender")}
          value={value.gender}
          onChange={(gender) => set({ gender })}
          options={["female", "male", "transgender"].map((g) => ({ value: g, label: optionLabel(i18n.language, g) }))}
        />
      </Field>
      </div>
      <div className="sm:col-span-2">
        <Field label={t("details.email")} hint={t("details.emailHint")}>
          <Input type="email" autoComplete="email" maxLength={320} value={value.contact_email ?? ""} onChange={(e) => set({ contact_email: e.target.value || null })} />
        </Field>
      </div>
    </div>
  );
}

/** State, district, village/town, pincode, address, rural/urban. */
export function AddressFields({ value, onChange, required = false }: Props & { required?: boolean }) {
  const { t, i18n } = useTranslation();
  const fields = useProfileFields();
  const states = fields.data?.find((f) => f.name === "state")?.options ?? [];
  const set = (patch: Partial<DetailsValue>) => onChange({ ...value, ...patch });
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <Field label={t("details.state")}>
        <Select required={required} value={value.state ?? ""} onChange={(e) => set({ state: e.target.value || null })}>
          <option value="">{t("details.choose")}</option>
          {states.map((s) => (
            <option key={s} value={s}>
              {optionLabel(i18n.language, s)}
            </option>
          ))}
        </Select>
      </Field>
      <Field label={t("details.district")}>
        <Input required={required} maxLength={80} value={value.district ?? ""} onChange={(e) => set({ district: e.target.value || null })} />
      </Field>
      <Field label={t("details.locality")}>
        <Input maxLength={120} autoComplete="address-level3" value={value.locality ?? ""} onChange={(e) => set({ locality: e.target.value || null })} />
      </Field>
      <Field label={t("details.pincode")}>
        <Input
          inputMode="numeric"
          pattern="[1-9][0-9]{5}"
          maxLength={6}
          autoComplete="postal-code"
          value={value.pincode ?? ""}
          onChange={(e) => set({ pincode: e.target.value.replace(/\D/g, "") || null })}
        />
      </Field>
      <div className="sm:col-span-2">
        <Field label={t("details.address")} hint={t("details.optional")}>
          <Input maxLength={255} autoComplete="street-address" value={value.address_line ?? ""} onChange={(e) => set({ address_line: e.target.value || null })} />
        </Field>
      </div>
      <div className="sm:col-span-2">
        <Field label={t("details.residence")} group>
          <Segmented
            label={t("details.residence")}
            value={value.residence}
            onChange={(residence) => set({ residence })}
            options={[
              { value: "rural", label: optionLabel(i18n.language, "rural") },
              { value: "urban", label: optionLabel(i18n.language, "urban") },
            ]}
          />
        </Field>
      </div>
    </div>
  );
}

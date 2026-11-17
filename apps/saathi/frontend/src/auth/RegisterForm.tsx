import { ArrowLeft, ArrowRight, Check } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { useRegister, useRequestOtp } from "../api/hooks";
import type { User } from "../api/types";
import { AddressFields, PersonalFields, type DetailsValue } from "../components/DetailsFields";
import { Button, cx, ErrorText, Field, Input } from "../components/ui";
import { PhoneInput } from "../components/PhoneInput";

const STEPS = ["about", "address", "verify"] as const;

/** Three short steps: who you are, where you live, verify your mobile (with consent). */
export function RegisterForm({ onDone }: { onDone: (user: User) => void }) {
  const { t } = useTranslation();
  const [step, setStep] = useState(0);
  const [details, setDetails] = useState<DetailsValue>({ display_name: "" });
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [consent, setConsent] = useState(false);
  const [codeSent, setCodeSent] = useState(false);
  const requestOtp = useRequestOtp();
  const register = useRegister();

  const next = (event: FormEvent) => {
    event.preventDefault();
    if (step < 2) {
      setStep(step + 1);
      return;
    }
    if (!codeSent) requestOtp.mutate(phone, { onSuccess: () => setCodeSent(true) });
    else register.mutate({ ...details, phone, code, consent: true }, { onSuccess: onDone });
  };

  return (
    <form onSubmit={next} className="space-y-6">
      <ol className="flex items-center gap-2" aria-label={t("register.progress")}>
        {STEPS.map((id, i) => (
          <li key={id} className="flex flex-1 items-center gap-2">
            <span
              className={cx(
                "flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-bold transition",
                i < step && "bg-brand-500 text-white",
                i === step && "bg-brand-700 text-white ring-4 ring-brand-100",
                i > step && "bg-stone-200 text-stone-500",
              )}
            >
              {i < step ? <Check className="h-3.5 w-3.5" aria-hidden /> : i + 1}
            </span>
            <span className={cx("hidden text-xs font-semibold sm:block", i === step ? "text-brand-900" : "text-stone-500")}>{t(`register.step.${id}`)}</span>
            {i < STEPS.length - 1 && <span className={cx("h-0.5 flex-1 rounded", i < step ? "bg-brand-400" : "bg-stone-200")} />}
          </li>
        ))}
      </ol>

      <div key={step} className="animate-fade-up">
        {step === 0 && (
          <div className="space-y-4">
            <PersonalFields value={details} onChange={setDetails} />
          </div>
        )}
        {step === 1 && <AddressFields value={details} onChange={setDetails} required />}
        {step === 2 && (
          <div className="space-y-4">
            <Field label={t("login.phone")} hint={t("login.phoneHint")}>
              <PhoneInput value={phone} onChange={setPhone} disabled={codeSent} />
            </Field>
            {codeSent && (
              <Field label={t("login.code")} hint={t("login.codeSent", { phone })}>
                <Input
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  pattern="\d{6}"
                  maxLength={6}
                  required
                  autoFocus
                  value={code}
                  onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
                  className="py-3 text-center font-mono text-2xl tracking-[0.5em]"
                  placeholder="••••••"
                />
              </Field>
            )}
            <label className="flex cursor-pointer items-start gap-3 rounded-xl bg-brand-50 p-4 text-sm text-brand-900">
              <input type="checkbox" required className="mt-0.5 h-4 w-4 accent-brand-600" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
              <span>{t("register.consent")}</span>
            </label>
          </div>
        )}
      </div>

      <ErrorText error={requestOtp.error ?? register.error} />

      <div className="flex gap-3">
        {step > 0 && (
          <Button type="button" variant="secondary" onClick={() => setStep(step - 1)} disabled={codeSent && register.isPending}>
            <ArrowLeft className="h-4 w-4" aria-hidden />
            {t("common.back")}
          </Button>
        )}
        <Button type="submit" className="flex-1 py-3" loading={requestOtp.isPending || register.isPending}>
          {step < 2 ? t("register.next") : codeSent ? t("register.create") : t("login.sendCode")}
          {step < 2 && <ArrowRight className="h-4 w-4" aria-hidden />}
        </Button>
      </div>
    </form>
  );
}

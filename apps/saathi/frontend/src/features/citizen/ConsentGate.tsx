import { Download, Lock, ShieldCheck, Target } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useGiveConsent } from "../../api/hooks";
import type { Citizen } from "../../api/types";
import { Button, Card, ErrorText, Notice } from "../../components/ui";

export function ConsentGate({ citizen }: { citizen: Citizen }) {
  const { t } = useTranslation();
  const consent = useGiveConsent(citizen.id);
  const points = [
    { icon: Target, text: t("consent.body1") },
    { icon: Lock, text: t("consent.body2") },
    { icon: Download, text: t("consent.body3") },
  ];
  return (
    <Card className="mx-auto max-w-2xl animate-fade-up p-6 sm:p-10">
      <div className="flex flex-col items-center text-center">
        <span className="flex h-16 w-16 items-center justify-center rounded-2xl bg-gradient-to-br from-brand-500 to-brand-700 text-white shadow-lift">
          <ShieldCheck className="h-8 w-8" aria-hidden />
        </span>
        <h2 className="mt-5 text-2xl font-bold tracking-tight text-brand-950">{t("consent.title")}</h2>
        <p className="mt-1 text-stone-600">{t("consent.subtitle")}</p>
      </div>
      {!citizen.is_self && (
        <div className="mt-6">
          <Notice tone="blue">{t("consent.helperNote")}</Notice>
        </div>
      )}
      <ul className="mt-6 space-y-3">
        {points.map(({ icon: Icon, text }) => (
          <li key={text} className="flex gap-3 rounded-2xl bg-stone-50 p-4">
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-white text-brand-600 shadow-sm">
              <Icon className="h-4.5 w-4.5" aria-hidden />
            </span>
            <p className="text-sm leading-relaxed text-stone-700">{text}</p>
          </li>
        ))}
      </ul>
      <ErrorText error={consent.error} />
      <Button className="mt-6 w-full py-3" onClick={() => consent.mutate()} loading={consent.isPending}>
        {t("consent.agree")}
      </Button>
    </Card>
  );
}

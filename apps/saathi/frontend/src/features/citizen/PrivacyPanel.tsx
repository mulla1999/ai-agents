import { Download, ShieldCheck, Trash2 } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router";
import { api } from "../../api/client";
import { useDeleteMyAccount, useEraseCitizen } from "../../api/hooks";
import type { Citizen } from "../../api/types";
import { Button, Card, ErrorText, formatDate } from "../../components/ui";

export function PrivacyPanel({ citizen }: { citizen: Citizen }) {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const deleteAccount = useDeleteMyAccount();
  const erase = useEraseCitizen();
  const [exportError, setExportError] = useState<unknown>(null);

  const download = async () => {
    setExportError(null);
    try {
      const data = await api<unknown>(`/citizens/${citizen.id}/export`);
      const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }));
      const link = document.createElement("a");
      link.href = url;
      link.download = `saathi-data-${citizen.id}.json`;
      link.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      setExportError(error);
    }
  };

  const remove = () => {
    if (!window.confirm(`${t("common.confirm")}\n\n${t("privacy.deleteWarning")}`)) return;
    if (citizen.is_self) deleteAccount.mutate(undefined, { onSuccess: () => navigate("/login") });
    else erase.mutate(citizen.id, { onSuccess: () => navigate("/citizens") });
  };

  return (
    <div className="grid max-w-4xl gap-5 md:grid-cols-2">
      <Card className="flex flex-col">
        <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-brand-50 text-brand-600">
          <Download className="h-5 w-5" aria-hidden />
        </span>
        <h2 className="mt-4 font-bold text-brand-950">{t("privacy.title")}</h2>
        {citizen.consent_at && (
          <p className="mt-1 flex items-center gap-1.5 text-sm text-stone-600">
            <ShieldCheck className="h-4 w-4 text-emerald-600" aria-hidden />
            {t("privacy.consentGiven", { date: formatDate(citizen.consent_at, i18n.language) })}
          </p>
        )}
        <p className="mt-2 text-sm text-stone-600">{t("privacy.exportHint")}</p>
        <div className="mt-auto pt-5">
          <Button variant="secondary" onClick={download}>
            <Download className="h-4 w-4" aria-hidden />
            {t("privacy.export")}
          </Button>
          <ErrorText error={exportError} />
        </div>
      </Card>
      <Card className="flex flex-col ring-red-200">
        <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-red-50 text-red-600">
          <Trash2 className="h-5 w-5" aria-hidden />
        </span>
        <h2 className="mt-4 font-bold text-brand-950">{citizen.is_self ? t("privacy.deleteSelf") : t("privacy.deleteOther")}</h2>
        <p className="mt-2 text-sm text-stone-600">{t("privacy.deleteWarning")}</p>
        <div className="mt-auto pt-5">
          <Button variant="danger" onClick={remove} loading={deleteAccount.isPending || erase.isPending}>
            <Trash2 className="h-4 w-4" aria-hidden />
            {t("common.delete")}
          </Button>
          <ErrorText error={deleteAccount.error ?? erase.error} />
        </div>
      </Card>
    </div>
  );
}

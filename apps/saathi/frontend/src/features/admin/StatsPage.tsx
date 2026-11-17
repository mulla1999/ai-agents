import { useTranslation } from "react-i18next";
import { useStats } from "../../api/hooks";
import { BarChart3 } from "lucide-react";
import { Card, ErrorText, PageHeader, Spinner } from "../../components/ui";

export function StatsPage() {
  const { t } = useTranslation();
  const stats = useStats();
  if (stats.isPending) return <Spinner />;
  if (stats.isError) return <ErrorText error={stats.error} />;
  const s = stats.data;

  return (
    <div className="animate-fade-up space-y-6">
      <PageHeader icon={BarChart3} title={t("admin.stats")} subtitle={t("admin.statsSubtitle")} />
      <div className="grid gap-4 sm:grid-cols-2">
        <Breakdown title={t("admin.usersByRole")} rows={s.users_by_role} label={(k) => t(`roles.${k}`)} />
        <Card>
          <h2 className="mb-3 font-bold text-brand-950">{t("admin.citizens")}</h2>
          <p className="text-sm">
            {s.citizens} · {s.citizens_with_consent} {t("admin.withConsent")}
          </p>
          <p className="mt-3 text-sm">
            {t("admin.messages7d")}: {s.chat_messages_last_7_days}
          </p>
        </Card>
        <Breakdown title={t("admin.applicationsByStatus")} rows={s.applications_by_status} label={(k) => t(`status.${k}`)} />
        <Breakdown title={t("admin.schemesByStatus")} rows={s.schemes_by_status} label={(k) => t(`status.${k}`)} />
      </div>
    </div>
  );
}

function Breakdown({ title, rows, label }: { title: string; rows: Record<string, number>; label: (key: string) => string }) {
  const entries = Object.entries(rows);
  return (
    <Card>
      <h2 className="mb-3 font-bold text-brand-950">{title}</h2>
      {entries.length === 0 ? (
        <p className="text-sm text-stone-500">—</p>
      ) : (
        <table className="w-full text-sm">
          <tbody>
            {entries.map(([key, count]) => (
              <tr key={key} className="border-b border-stone-100 last:border-0">
                <td className="py-1">{label(key)}</td>
                <td className="py-1 text-right tabular-nums">{count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Card>
  );
}

import { useTranslation } from "react-i18next";
import { Link } from "react-router";
import { useAdminSchemes } from "../../api/hooks";
import type { SchemeStatus } from "../../api/types";
import { BadgeCheck, BookOpenCheck, Plus } from "lucide-react";
import { schemeIcon } from "../../components/schemeIcon";
import { Badge, cx, ErrorText, PageHeader, Spinner } from "../../components/ui";

function SchemeIconTile({ tags }: { tags: string[] }) {
  const { icon: Icon, tint } = schemeIcon(tags);
  return (
    <span className={cx("flex h-9 w-9 shrink-0 items-center justify-center rounded-lg", tint)}>
      <Icon className="h-4.5 w-4.5" aria-hidden />
    </span>
  );
}

export const statusTone = (status: SchemeStatus) => (status === "verified" ? "green" : status === "draft" ? "amber" : "stone");

export function SchemesPage() {
  const { t } = useTranslation();
  const schemes = useAdminSchemes();

  return (
    <div className="animate-fade-up space-y-6">
      <PageHeader
        icon={BookOpenCheck}
        title={t("admin.schemes")}
        subtitle={t("admin.schemesSubtitle")}
        action={
          <Link to="/admin/schemes/new" className="inline-flex items-center gap-2 rounded-xl bg-brand-700 px-4 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-brand-800">
            <Plus className="h-4 w-4" aria-hidden />
            {t("admin.newScheme")}
          </Link>
        }
      />
      {schemes.isPending ? (
        <Spinner />
      ) : schemes.isError ? (
        <ErrorText error={schemes.error} />
      ) : (
        <div className="overflow-x-auto rounded-2xl bg-white shadow-card ring-1 ring-stone-200/70">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-stone-100 bg-stone-50/60 text-xs uppercase tracking-wide text-stone-500">
              <tr>
                <th className="px-4 py-3 font-semibold">{t("admin.schemes")}</th>
                <th className="px-4 py-3 font-semibold">Status</th>
                <th className="px-4 py-3 font-semibold">{t("admin.version")}</th>
                <th className="px-4 py-3 font-semibold">{t("admin.verifiedOn")}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-stone-100">
              {schemes.data.map((s) => (
                <tr key={s.id}>
                  <td className="px-4 py-3">
                    <Link to={`/admin/schemes/${s.id}`} className="flex items-center gap-3 font-semibold text-brand-800 hover:underline">
                      <SchemeIconTile tags={s.tags} />
                      {s.name}
                    </Link>
                    <span className="ml-12 block text-xs text-stone-500">{s.id}</span>
                  </td>
                  <td className="px-4 py-3">
                    <Badge tone={statusTone(s.status)} icon={s.status === "verified" ? BadgeCheck : undefined}>
                      {t(`status.${s.status}`)}
                    </Badge>
                  </td>
                  <td className="px-4 py-3">{s.version}</td>
                  <td className="px-4 py-3">{s.verified_on ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

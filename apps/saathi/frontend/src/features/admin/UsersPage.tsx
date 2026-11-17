import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useUpdateUser, useUsers } from "../../api/hooks";
import type { Role } from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import { UserRound } from "lucide-react";
import { ErrorText, formatDate, Initials, Input, PageHeader, Select, Spinner } from "../../components/ui";

const ROLES: Role[] = ["citizen", "helper", "admin"];

export function UsersPage() {
  const { t, i18n } = useTranslation();
  const { user: me } = useAuth();
  const [query, setQuery] = useState("");
  const [role, setRole] = useState<Role | "">("");
  const users = useUsers(query.trim(), role);
  const update = useUpdateUser();

  return (
    <div className="animate-fade-up space-y-6">
      <PageHeader icon={UserRound} title={t("admin.users")} subtitle={t("admin.usersSubtitle")} />
      <div className="grid gap-2 sm:grid-cols-[1fr_200px]">
        <Input type="search" placeholder={t("common.search")} aria-label={t("common.search")} value={query} onChange={(e) => setQuery(e.target.value)} />
        <Select value={role} onChange={(e) => setRole(e.target.value as Role | "")} aria-label={t("admin.role")}>
          <option value="">{t("admin.allRoles")}</option>
          {ROLES.map((r) => (
            <option key={r} value={r}>
              {t(`roles.${r}`)}
            </option>
          ))}
        </Select>
      </div>
      <ErrorText error={update.error} />
      {users.isPending ? (
        <Spinner />
      ) : users.isError ? (
        <ErrorText error={users.error} />
      ) : (
        <div className="overflow-x-auto rounded-2xl bg-white shadow-card ring-1 ring-stone-200/70">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-stone-100 bg-stone-50/60 text-xs uppercase tracking-wide text-stone-500">
              <tr>
                <th className="px-4 py-3 font-semibold">{t("citizens.name")}</th>
                <th className="px-4 py-3 font-semibold">{t("admin.role")}</th>
                <th className="px-4 py-3 font-semibold">{t("admin.active")}</th>
                <th className="px-4 py-3 font-semibold">{t("admin.lastLogin")}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-stone-100">
              {users.data.map((u) => {
                const isMe = u.id === me?.id;
                return (
                  <tr key={u.id}>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-3">
                        <Initials name={u.display_name ?? u.email ?? u.phone ?? "?"} className="h-9 w-9 text-xs" />
                        <div>
                          <span className="font-semibold text-stone-900">{u.display_name ?? "—"}</span>
                          <span className="block text-xs text-stone-500">{u.email ?? u.phone}</span>
                        </div>
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <Select value={u.role} disabled={isMe || update.isPending} onChange={(e) => update.mutate({ id: u.id, patch: { role: e.target.value as Role } })}>
                        {ROLES.map((r) => (
                          <option key={r} value={r}>
                            {t(`roles.${r}`)}
                          </option>
                        ))}
                      </Select>
                    </td>
                    <td className="px-4 py-3">
                      <input
                        type="checkbox"
                        aria-label={t("admin.active")}
                        checked={u.is_active}
                        disabled={isMe || update.isPending}
                        onChange={(e) => update.mutate({ id: u.id, patch: { is_active: e.target.checked } })}
                      />
                    </td>
                    <td className="px-4 py-3 text-stone-600">{formatDate(u.last_login_at, i18n.language)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

import { BarChart3, BookOpenCheck, HeartHandshake, LogOut, UserRound, UsersRound } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useTranslation } from "react-i18next";
import { NavLink, Outlet, useNavigate } from "react-router";
import { useLogout } from "../api/hooks";
import { useAuth } from "../auth/AuthContext";
import { LanguageSwitch } from "./LanguageSwitch";
import { Logo } from "./Logo";
import { cx, Initials } from "./ui";

export function Layout() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const logout = useLogout();
  const navigate = useNavigate();

  const links: { to: string; label: string; icon: LucideIcon }[] = [];
  if (user) {
    links.push({ to: "/me", label: t("nav.myHelp"), icon: HeartHandshake });
    if (user.role === "helper" || user.role === "admin") links.push({ to: "/citizens", label: t("nav.citizens"), icon: UsersRound });
    if (user.role === "admin") {
      links.push(
        { to: "/admin/schemes", label: t("nav.schemes"), icon: BookOpenCheck },
        { to: "/admin/users", label: t("nav.users"), icon: UserRound },
        { to: "/admin/stats", label: t("nav.stats"), icon: BarChart3 },
      );
    }
  }
  const name = user?.display_name ?? user?.email ?? user?.phone ?? "";

  return (
    <div className="flex min-h-screen flex-col">
      <header className="sticky top-0 z-20 border-b border-stone-200/70 bg-white/85 backdrop-blur-md">
        <div className="mx-auto flex max-w-6xl items-center gap-4 px-4 py-3">
          <NavLink to="/" aria-label={t("app.name")}>
            <Logo />
          </NavLink>
          <nav className="ml-4 hidden flex-1 items-center gap-1 md:flex">
            {links.map((link) => (
              <NavItem key={link.to} {...link} />
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-2">
            <LanguageSwitch />
            {user && (
              <>
                <NavLink
                  to="/account"
                  className="flex items-center gap-2 rounded-full py-1 pl-1 pr-3 transition hover:bg-stone-100"
                  title={t("nav.account")}
                >
                  <Initials name={name} className="h-8 w-8 text-xs" />
                  <span className="hidden max-w-[10rem] truncate text-sm font-medium text-stone-700 lg:block">{name}</span>
                </NavLink>
                <button
                  type="button"
                  aria-label={t("nav.logout")}
                  title={t("nav.logout")}
                  className="rounded-full p-2 text-stone-500 transition hover:bg-stone-100 hover:text-stone-800"
                  onClick={() => logout.mutate(undefined, { onSettled: () => navigate("/login") })}
                >
                  <LogOut className="h-4 w-4" aria-hidden />
                </button>
              </>
            )}
          </div>
        </div>
        {links.length > 1 && (
          <nav className="flex gap-1 overflow-x-auto border-t border-stone-100 px-3 py-2 md:hidden">
            {links.map((link) => (
              <NavItem key={link.to} {...link} />
            ))}
          </nav>
        )}
      </header>

      <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-6 sm:py-8">
        <Outlet />
      </main>

      <footer className="border-t border-stone-200/70 py-6 text-center text-xs text-stone-500">{t("app.notGovt")}</footer>
    </div>
  );
}

function NavItem({ to, label, icon: Icon }: { to: string; label: string; icon: LucideIcon }) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) =>
        cx(
          "flex shrink-0 items-center gap-2 rounded-full px-3.5 py-2 text-sm font-medium transition",
          isActive ? "bg-brand-700 text-white shadow-sm" : "text-stone-600 hover:bg-stone-100 hover:text-stone-900",
        )
      }
    >
      <Icon className="h-4 w-4" aria-hidden />
      {label}
    </NavLink>
  );
}

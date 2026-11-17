import { useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  BarChart3,
  Bird,
  Bot,
  Briefcase,
  ClipboardCheck,
  FileText,
  Gauge,
  KeyRound,
  ListChecks,
  LogOut,
  Mail,
  Menu,
  MessageCircle,
  PenLine,
  Plug,
  ScrollText,
  Settings2,
  ShieldCheck,
  Sparkles,
  UserRound,
  Users,
  X,
} from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { NavLink, useLocation, useNavigate } from "react-router";
import { api } from "../api/client";
import type { User } from "../api/types";
import { isAdmin } from "../auth";
import { ChatPanel } from "./chat/ChatPanel";
import { cx } from "./ui";
import { BRAND, TAGLINE } from "../brand";

type Item = { to: string; label: string; icon: typeof Activity; end?: boolean; superadmin?: boolean };

const SECTIONS: { title: string; items: Item[] }[] = [
  {
    title: "Search",
    items: [
      { to: "/", label: "Dashboard", icon: Gauge, end: true },
      { to: "/assistant", label: "Assistant", icon: Sparkles },
      { to: "/jobs", label: "Job Discovery", icon: Briefcase },
    ],
  },
  {
    title: "Apply",
    items: [
      { to: "/resume-builder", label: "Resume Builder", icon: PenLine },
      { to: "/resumes", label: "Resume Studio", icon: FileText },
      { to: "/queue", label: "Application Queue", icon: ClipboardCheck },
      { to: "/tracker", label: "Application Tracker", icon: ListChecks },
      { to: "/outreach", label: "Recruiter Outreach", icon: Mail },
    ],
  },
  {
    title: "Setup",
    items: [
      { to: "/profile", label: "Profile & Preferences", icon: UserRound },
      { to: "/integrations", label: "Integrations", icon: Plug },
      { to: "/automation", label: "Automation", icon: Settings2 },
      { to: "/audit", label: "Activity Log", icon: Activity },
      { to: "/account", label: "Account & security", icon: KeyRound },
    ],
  },
];

const ADMIN: Item[] = [
  { to: "/admin", label: "Overview", icon: BarChart3, end: true },
  { to: "/admin/users", label: "Users", icon: Users },
  { to: "/admin/settings", label: "Platform settings", icon: KeyRound, superadmin: true },
  { to: "/admin/audit", label: "Platform audit", icon: ScrollText },
];

function NavItem({ item, onClick }: { item: Item; onClick: () => void }) {
  const Icon = item.icon;
  return (
    <li>
      <NavLink
        to={item.to}
        end={item.end}
        onClick={onClick}
        className={({ isActive }) =>
          cx(
            "group flex items-center gap-3 rounded-lg px-3 py-2 text-[0.8125rem] font-medium transition",
            isActive ? "bg-white/10 text-white shadow-[inset_0_0_0_1px_rgb(255_255_255/0.08)]" : "text-slate-400 hover:bg-white/5 hover:text-slate-100",
          )
        }
      >
        {({ isActive }) => (
          <>
            <Icon className={cx("size-4 shrink-0 transition", isActive ? "text-indigo-300" : "text-slate-500 group-hover:text-slate-300")} aria-hidden />
            {item.label}
          </>
        )}
      </NavLink>
    </li>
  );
}

function Logo() {
  return (
    <span className="flex items-center gap-2.5">
      <span className="grid size-8 place-items-center rounded-xl bg-gradient-to-br from-indigo-400 to-violet-600 shadow-lg shadow-indigo-900/40">
        <Bird className="size-4 text-white" aria-hidden />
      </span>
      <span className="leading-tight">
        <span className="block text-[0.9375rem] font-semibold tracking-tight text-white">{BRAND}</span>
        <span className="block text-[0.6875rem] text-slate-400">{TAGLINE}</span>
      </span>
    </span>
  );
}

export function Layout({ children, user }: { children: ReactNode; user: User }) {
  const [open, setOpen] = useState(false);
  const [chatOpen, setChatOpen] = useState(false);
  const client = useQueryClient();
  const navigate = useNavigate();
  const location = useLocation();
  const close = () => setOpen(false);
  const onAssistantPage = location.pathname.startsWith("/assistant");
  const initial = (user.full_name || user.email).slice(0, 1).toUpperCase();

  // Phone menu: a drawer over whatever is on screen. Close it on navigation and Escape, and stop the
  // page behind it from scrolling while it is open.
  useEffect(() => setOpen(false), [location.pathname]);
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = overflow;
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div className="min-h-screen md:flex">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-white focus:px-3 focus:py-2">
        Skip to content
      </a>
      <header className="sticky top-0 z-30 flex items-center justify-between bg-slate-950 px-4 py-3 md:hidden">
        <Logo />
        <button type="button" aria-label="Open menu" aria-expanded={open} onClick={() => setOpen(true)} className="rounded-lg p-2 text-slate-300 hover:bg-white/10">
          <Menu className="size-6" />
        </button>
      </header>
      {open && <button type="button" aria-label="Close menu" tabIndex={-1} onClick={close} className="fixed inset-0 z-40 bg-slate-950/60 backdrop-blur-[1px] md:hidden" />}
      <nav
        aria-label="Main"
        className={cx(
          "shrink-0 flex-col bg-slate-950 bg-[radial-gradient(600px_300px_at_0%_0%,rgb(79_70_229/0.25),transparent_60%)]",
          // phone: a drawer from the left, over the page; desktop: the usual sidebar
          "fixed inset-y-0 left-0 z-50 w-[85vw] max-w-xs shadow-2xl md:sticky md:bottom-auto md:z-auto md:flex md:h-screen md:w-64 md:max-w-none md:shadow-none",
          open ? "flex" : "hidden",
        )}
      >
        <div className="flex items-center justify-between px-4 py-3 md:hidden">
          <Logo />
          <button type="button" aria-label="Close menu" onClick={close} className="rounded-lg p-2 text-slate-300 hover:bg-white/10">
            <X className="size-6" />
          </button>
        </div>
        <div className="hidden px-5 pb-4 pt-5 md:block">
          <Logo />
        </div>
        <div className="scroll-soft flex min-h-0 flex-1 flex-col overflow-y-auto px-3">
          <button
            type="button"
            onClick={() => {
              close();
              navigate("/assistant");
            }}
            className="mb-4 flex items-center gap-3 rounded-xl bg-gradient-to-r from-indigo-500/20 to-violet-500/10 px-3 py-2.5 text-left ring-1 ring-inset ring-indigo-400/20 transition hover:from-indigo-500/30"
          >
            <span className="grid size-8 place-items-center rounded-lg bg-indigo-500/20">
              <Bot className="size-4 text-indigo-200" aria-hidden />
            </span>
            <span className="leading-tight">
              <span className="block text-sm font-medium text-white">Ask the assistant</span>
              <span className="block text-xs text-slate-400">Find jobs, apply, email recruiters</span>
            </span>
          </button>
          {SECTIONS.map((section) => (
            <div key={section.title} className="mb-4">
              <p className="px-3 pb-1.5 text-[0.6875rem] font-semibold uppercase tracking-wider text-slate-500">{section.title}</p>
              <ul className="space-y-0.5">
                {section.items.map((item) => (
                  <NavItem key={item.to} item={item} onClick={close} />
                ))}
              </ul>
            </div>
          ))}
          {isAdmin(user) && (
            <div className="mb-4">
              <p className="flex items-center gap-1.5 px-3 pb-1.5 text-[0.6875rem] font-semibold uppercase tracking-wider text-slate-500">
                <ShieldCheck className="size-3.5" aria-hidden /> Administration
              </p>
              <ul className="space-y-0.5">
                {ADMIN.filter((n) => !n.superadmin || user.role === "superadmin").map((item) => (
                  <NavItem key={item.to} item={item} onClick={close} />
                ))}
              </ul>
            </div>
          )}
          <div className="mt-auto border-t border-white/10 py-3">
            <NavLink to="/account" onClick={close} className={({ isActive }) => cx("block rounded-lg px-2 py-2 transition hover:bg-white/5", isActive && "bg-white/10")}>
              <span className="flex items-center gap-2.5">
                <span className="grid size-9 shrink-0 place-items-center rounded-full bg-gradient-to-br from-sky-400 to-indigo-500 text-sm font-semibold text-white">{initial}</span>
                <span className="min-w-0">
                  <span className="block truncate text-sm font-medium text-slate-100">{user.full_name || user.email}</span>
                  <span className="flex items-center gap-1.5">
                    {user.full_name && <span className="truncate text-xs text-slate-400">{user.email}</span>}
                    {user.role !== "user" && <span className="rounded-full bg-indigo-400/15 px-1.5 text-[0.625rem] font-medium uppercase tracking-wide text-indigo-200">{user.role}</span>}
                  </span>
                </span>
              </span>
            </NavLink>
            <button
              type="button"
              className="mt-1 flex w-full items-center gap-3 rounded-lg px-3 py-2 text-[0.8125rem] font-medium text-slate-400 transition hover:bg-white/5 hover:text-slate-100"
              onClick={async () => {
                await api("/auth/logout", { method: "POST" }).catch(() => undefined);
                client.setQueryData(["auth"], { authenticated: false, user: null });
                client.removeQueries({ predicate: (q) => q.queryKey[0] !== "auth" });
                navigate("/login");
              }}
            >
              <LogOut className="size-4" aria-hidden /> Sign out
            </button>
          </div>
        </div>
      </nav>
      <main id="main" className={cx("min-w-0 flex-1", onAssistantPage ? "p-0 md:p-4" : "px-4 pb-24 pt-6 md:px-10 md:pb-24 md:pt-8")}>
        <div className={cx("mx-auto", onAssistantPage ? "max-w-none" : "max-w-7xl")}>{children}</div>
      </main>

      {!onAssistantPage && (
        <>
          <button
            type="button"
            aria-label={chatOpen ? "Close assistant" : "Open assistant"}
            onClick={() => setChatOpen(!chatOpen)}
            className="fixed bottom-5 right-5 z-40 grid size-14 place-items-center rounded-full bg-gradient-to-br from-indigo-500 to-violet-600 text-white shadow-lift transition hover:scale-105"
          >
            {chatOpen ? <X className="size-6" /> : <MessageCircle className="size-6" />}
          </button>
          {chatOpen && (
            <div className="rise-in fixed inset-x-3 bottom-24 top-16 z-40 overflow-hidden rounded-2xl bg-white shadow-2xl ring-1 ring-slate-900/10 sm:inset-x-auto sm:right-5 sm:top-auto sm:h-[min(42rem,calc(100vh-8rem))] sm:supports-[height:100dvh]:h-[min(42rem,calc(100dvh-8rem))] sm:w-[26rem]">
              <ChatPanel
                compact
                onExpand={() => {
                  setChatOpen(false);
                  navigate("/assistant");
                }}
              />
            </div>
          )}
        </>
      )}
    </div>
  );
}

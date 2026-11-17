import { ArrowLeft, ArrowRight, ClipboardList, FileText, MapPin, MessageCircleHeart, ShieldCheck, Sparkles } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Link, NavLink, Navigate, Route, Routes, useParams } from "react-router";
import { useCitizen, useProfileFields } from "../../api/hooks";
import type { Citizen } from "../../api/types";
import { cx, ErrorText, Spinner } from "../../components/ui";
import { ApplicationsPanel } from "./ApplicationsPanel";
import { ChatPanel } from "./ChatPanel";
import { ConsentGate } from "./ConsentGate";
import { EligibilityPanel } from "./EligibilityPanel";
import { PrivacyPanel } from "./PrivacyPanel";
import { ProfileForm } from "./ProfileForm";

const TABS: { id: string; icon: LucideIcon }[] = [
  { id: "chat", icon: MessageCircleHeart },
  { id: "schemes", icon: Sparkles },
  { id: "profile", icon: FileText },
  { id: "applications", icon: ClipboardList },
  { id: "privacy", icon: ShieldCheck },
];

/** Mounted at /me/* (the signed-in user's own record) and /citizens/:citizenId/* (a managed record). */
export function CitizenWorkspace() {
  const { citizenId } = useParams();
  const citizen = useCitizen(citizenId ?? "self");

  if (citizen.isPending) return <Spinner />;
  if (citizen.isError) return <ErrorText error={citizen.error} />;
  const data = citizen.data;

  return (
    <div className="space-y-6 animate-fade-up">
      <WorkspaceHeader citizen={data} />
      <Tabs />
      <Routes>
        <Route index element={<Navigate to="chat" replace />} />
        <Route path="chat" element={<Gated citizen={data}><ChatPanel citizen={data} /></Gated>} />
        <Route path="schemes" element={<Gated citizen={data}><EligibilityPanel citizen={data} /></Gated>} />
        <Route path="profile" element={<Gated citizen={data}><ProfileForm citizen={data} /></Gated>} />
        <Route path="applications" element={<Gated citizen={data}><ApplicationsPanel citizen={data} /></Gated>} />
        <Route path="privacy" element={<PrivacyPanel citizen={data} />} />
      </Routes>
    </div>
  );
}

function WorkspaceHeader({ citizen }: { citizen: Citizen }) {
  const { t } = useTranslation();
  const fields = useProfileFields();
  const total = fields.data?.length ?? 0;
  const known = Object.keys(citizen.profile).length;
  const percent = total ? Math.round((known / total) * 100) : 0;

  return (
    <section className="relative overflow-hidden rounded-3xl bg-gradient-to-br from-brand-700 to-brand-900 p-6 text-white shadow-lift sm:p-8">
      <div className="bg-dots pointer-events-none absolute inset-0" aria-hidden />
      <div className="pointer-events-none absolute -right-16 -top-20 h-56 w-56 rounded-full bg-saffron-400/25 blur-3xl" aria-hidden />
      <div className="relative flex flex-wrap items-center gap-5">
        {!citizen.is_self && (
          <Link to="/citizens" className="rounded-full bg-white/10 p-2 transition hover:bg-white/20" aria-label={t("common.back")}>
            <ArrowLeft className="h-5 w-5" aria-hidden />
          </Link>
        )}
        <span className="flex h-14 w-14 items-center justify-center rounded-full bg-white/15 text-lg font-bold ring-2 ring-white/30">
          {initialsOf(citizen.display_name)}
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-sm text-brand-100">{citizen.is_self ? t("workspace.greeting") : t("workspace.helping")}</p>
          <h1 className="truncate text-2xl font-bold tracking-tight sm:text-3xl">{citizen.display_name}</h1>
        </div>
        <div className="w-full sm:w-64">
          <div className="flex items-center justify-between text-xs font-medium text-brand-100">
            <span>{t("workspace.profileComplete")}</span>
            <span>{percent}%</span>
          </div>
          <div className="mt-2 h-2 overflow-hidden rounded-full bg-white/15">
            <div className="h-full rounded-full bg-gradient-to-r from-saffron-300 to-saffron-500 transition-all" style={{ width: `${percent}%` }} />
          </div>
          <p className="mt-2 text-xs text-brand-100">{t("workspace.profileHint")}</p>
        </div>
      </div>
      {(!citizen.date_of_birth || !citizen.profile.state || !citizen.profile.district) && citizen.consent_at && (
        <Link
          to="profile"
          className="relative mt-5 flex items-center gap-3 rounded-2xl bg-white/10 px-4 py-3 text-sm ring-1 ring-inset ring-white/15 transition hover:bg-white/15"
        >
          <MapPin className="h-5 w-5 shrink-0 text-saffron-300" aria-hidden />
          <span className="flex-1">{t("workspace.completeDetails")}</span>
          <ArrowRight className="h-4 w-4" aria-hidden />
        </Link>
      )}
    </section>
  );
}

function Tabs() {
  const { t } = useTranslation();
  return (
    <nav className="flex gap-1 overflow-x-auto rounded-2xl bg-white p-1.5 shadow-card ring-1 ring-stone-200/70">
      {TABS.map(({ id, icon: Icon }) => (
        <NavLink
          key={id}
          to={id}
          className={({ isActive }) =>
            cx(
              "flex flex-1 shrink-0 items-center justify-center gap-2 whitespace-nowrap rounded-xl px-4 py-2.5 text-sm font-semibold transition",
              isActive ? "bg-brand-50 text-brand-800 ring-1 ring-inset ring-brand-200" : "text-stone-500 hover:bg-stone-50 hover:text-stone-800",
            )
          }
        >
          <Icon className="h-4 w-4" aria-hidden />
          {t(`tabs.${id}`)}
        </NavLink>
      ))}
    </nav>
  );
}

function Gated({ citizen, children }: { citizen: Citizen; children: ReactNode }) {
  return citizen.consent_at ? <>{children}</> : <ConsentGate citizen={citizen} />;
}

function initialsOf(name: string): string {
  return name.split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part[0]?.toUpperCase()).join("") || "?";
}

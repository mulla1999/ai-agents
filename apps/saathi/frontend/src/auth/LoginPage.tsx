import { ArrowLeft, FileCheck2, Languages, MessageCircle, ShieldCheck, Smartphone } from "lucide-react";
import { useState, type ComponentType, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Link, Navigate, useNavigate, useSearchParams } from "react-router";
import { useAuthConfig, useRequestOtp, useVerifyOtp } from "../api/hooks";
import type { Role } from "../api/types";
import { HeroIllustration } from "../components/illustrations";
import { LanguageSwitch } from "../components/LanguageSwitch";
import { Logo } from "../components/Logo";
import { Button, cx, ErrorText, Field, Input, Notice } from "../components/ui";
import { useAuth } from "./AuthContext";
import { PhoneInput } from "../components/PhoneInput";
import { RegisterForm } from "./RegisterForm";
import { homePathFor } from "./RequireRole";
import { WhatsAppLogin } from "./WhatsAppLogin";

type Method = "phone" | "whatsapp" | "google";
type Mode = "signin" | "register";

function safeNext(value: string | null): string | null {
  return value && value.startsWith("/") && !value.startsWith("//") ? value : null;
}

/** /login and /register: one screen, no page scroll on desktop; the form comes first on phones. */
export function LoginPage({ mode = "signin" }: { mode?: Mode }) {
  const { t } = useTranslation();
  const { user } = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const next = safeNext(params.get("next"));
  const query = next ? `?next=${encodeURIComponent(next)}` : "";

  if (user) return <Navigate to={next ?? homePathFor(user.role)} replace />;
  const done = (role: Role) => navigate(next ?? homePathFor(role), { replace: true });

  return (
    <div className="min-h-dvh lg:grid lg:h-dvh lg:grid-cols-[minmax(0,1.05fr)_minmax(0,1fr)] lg:overflow-hidden">
      <Hero />

      {/* compact brand bar on phones and tablets */}
      <div className="relative overflow-hidden bg-gradient-to-br from-brand-700 to-brand-950 px-4 pb-5 pt-4 text-white lg:hidden">
        <div className="bg-dots pointer-events-none absolute inset-0" aria-hidden />
        <div className="relative flex items-center justify-between">
          <Logo light />
          <LanguageSwitch dark />
        </div>
        <p className="relative mt-4 text-lg font-semibold leading-snug">
          {t("login.heroTitle1")} <span className="text-saffron-300">{t("login.heroTitle2")}</span>
        </p>
      </div>

      <main className="flex flex-col px-4 py-6 sm:px-8 lg:overflow-y-auto lg:py-8">
        <div className="hidden justify-end lg:flex">
          <LanguageSwitch />
        </div>
        <div className="mx-auto flex w-full max-w-md flex-1 animate-fade-up flex-col justify-center lg:py-6">
          <h1 className="text-2xl font-bold tracking-tight text-brand-950 sm:text-3xl">
            {mode === "signin" ? t("login.title") : t("register.title")}
          </h1>
          <p className="mt-1.5 text-stone-600">{mode === "signin" ? t("login.subtitle") : t("register.subtitle")}</p>

          <div role="tablist" className="mt-6 grid grid-cols-2 gap-1 rounded-2xl bg-stone-200/60 p-1">
            {(["signin", "register"] as const).map((m) => (
              <Link
                key={m}
                role="tab"
                aria-selected={mode === m}
                to={(m === "signin" ? "/login" : "/register") + query}
                replace
                className={cx(
                  "rounded-xl px-3 py-2.5 text-center text-sm font-semibold transition",
                  mode === m ? "bg-white text-brand-800 shadow-sm" : "text-stone-600 hover:text-stone-900",
                )}
              >
                {m === "signin" ? t("login.signIn") : t("login.createAccount")}
              </Link>
            ))}
          </div>

          <div className="mt-4 rounded-3xl bg-white p-6 shadow-lift ring-1 ring-stone-200/70 sm:p-7">
            {mode === "signin" ? <SignIn next={next} onDone={done} /> : <RegisterForm onDone={(u) => done(u.role)} />}
          </div>

          <div className="mt-4">
            <Notice tone="amber" icon={ShieldCheck}>
              <span className="text-xs">{t("login.neverShare")}</span>
            </Notice>
          </div>
          <p className="mt-4 text-center text-xs text-stone-500">{t("app.notGovt")}</p>
        </div>
      </main>
    </div>
  );
}

function SignIn({ next, onDone }: { next: string | null; onDone: (role: Role) => void }) {
  const { t } = useTranslation();
  const config = useAuthConfig();
  const [params] = useSearchParams();
  const [method, setMethod] = useState<Method>("phone");
  const errorParam = params.get("error");

  const methods: { id: Method; label: string; icon: ComponentType<{ className?: string }> }[] = [
    { id: "phone", label: t("login.tabPhone"), icon: Smartphone },
  ];
  if (config.data?.whatsapp_login_enabled) methods.push({ id: "whatsapp", label: "WhatsApp", icon: MessageCircle });
  if (config.data?.google_enabled) methods.push({ id: "google", label: "Google", icon: GoogleIcon });

  return (
    <div className="space-y-5">
      {errorParam && <ErrorText error={new Error(t(errorParam === "disabled" ? "login.disabled" : "login.googleFailed"))} />}
      {methods.length > 1 && (
        <div role="tablist" className={cx("grid gap-1 rounded-xl bg-stone-100 p-1", methods.length === 2 ? "grid-cols-2" : "grid-cols-3")}>
          {methods.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              type="button"
              role="tab"
              aria-selected={method === id}
              onClick={() => setMethod(id)}
              className={cx(
                "flex items-center justify-center gap-2 rounded-lg px-3 py-2 text-sm font-semibold transition",
                method === id ? "bg-white text-brand-800 shadow-sm" : "text-stone-500 hover:text-stone-800",
              )}
            >
              <Icon className="h-4 w-4" aria-hidden />
              {label}
            </button>
          ))}
        </div>
      )}
      {method === "phone" && <PhoneLogin onDone={onDone} />}
      {method === "whatsapp" && <WhatsAppLogin onSignedIn={(u) => onDone(u.role)} />}
      {method === "google" && (
        <a
          href={`/api/auth/google/login?next=${encodeURIComponent(next ?? "/")}`}
          className="flex w-full items-center justify-center gap-3 rounded-xl bg-white px-4 py-3 text-sm font-semibold text-stone-800 shadow-sm ring-1 ring-stone-200 transition hover:bg-stone-50"
        >
          <GoogleIcon className="h-5 w-5" />
          {t("login.google")}
        </a>
      )}
      <p className="text-center text-sm text-stone-600">
        {t("login.noAccount")}{" "}
        <Link to="/register" replace className="font-semibold text-brand-700 hover:underline">
          {t("login.createAccount")}
        </Link>
      </p>
    </div>
  );
}

function Hero() {
  const { t } = useTranslation();
  const features = [
    { icon: Languages, title: t("login.feature1Title") },
    { icon: ShieldCheck, title: t("login.feature2Title") },
    { icon: FileCheck2, title: t("login.feature3Title") },
  ];
  return (
    <aside className="relative hidden overflow-hidden bg-gradient-to-br from-brand-700 via-brand-800 to-brand-950 p-10 text-white lg:flex lg:flex-col xl:p-12">
      <div className="bg-dots pointer-events-none absolute inset-0" aria-hidden />
      <div className="pointer-events-none absolute -right-24 -top-24 h-72 w-72 rounded-full bg-saffron-400/20 blur-3xl" aria-hidden />
      <div className="pointer-events-none absolute -bottom-32 -left-20 h-80 w-80 rounded-full bg-brand-400/25 blur-3xl" aria-hidden />

      <Logo light className="relative" />

      <div className="relative mt-10 max-w-xl">
        <span className="inline-flex items-center gap-2 rounded-full bg-white/10 px-3 py-1 text-xs font-semibold text-brand-100 ring-1 ring-inset ring-white/15">
          <span className="h-1.5 w-1.5 rounded-full bg-saffron-400" />
          {t("login.eyebrow")}
        </span>
        <h2 className="mt-4 text-4xl font-bold leading-tight tracking-tight xl:text-5xl">
          {t("login.heroTitle1")} <span className="text-saffron-300">{t("login.heroTitle2")}</span>
        </h2>
        <p className="mt-4 max-w-lg text-base text-brand-100 xl:text-lg">{t("login.heroText")}</p>
      </div>

      {/* The illustration takes whatever height is left, so the panel never overflows the screen. */}
      <div className="relative flex min-h-0 flex-1 items-center justify-center py-6">
        <HeroIllustration className="h-full max-h-[400px] w-auto max-w-full" />
      </div>

      <ul className="relative flex flex-wrap gap-2">
        {features.map(({ icon: Icon, title }) => (
          <li key={title} className="flex items-center gap-2 rounded-full bg-white/[0.08] px-4 py-2 text-sm font-medium ring-1 ring-inset ring-white/10">
            <Icon className="h-4 w-4 text-saffron-300" aria-hidden />
            {title}
          </li>
        ))}
      </ul>
    </aside>
  );
}

function PhoneLogin({ onDone }: { onDone: (role: Role) => void }) {
  const { t } = useTranslation();
  const requestOtp = useRequestOtp();
  const verifyOtp = useVerifyOtp();
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [codeSent, setCodeSent] = useState(false);

  const sendCode = (event: FormEvent) => {
    event.preventDefault();
    requestOtp.mutate(phone, { onSuccess: () => setCodeSent(true) });
  };
  const verify = (event: FormEvent) => {
    event.preventDefault();
    verifyOtp.mutate({ phone, code }, { onSuccess: (u) => onDone(u.role) });
  };

  if (!codeSent) {
    return (
      <form onSubmit={sendCode} className="space-y-5">
        <Field label={t("login.phone")} hint={t("login.phoneHint")}>
          <PhoneInput value={phone} onChange={setPhone} />
        </Field>
        <ErrorText error={requestOtp.error} />
        <Button type="submit" className="w-full py-3" loading={requestOtp.isPending}>
          {t("login.sendCode")}
        </Button>
      </form>
    );
  }
  return (
    <form onSubmit={verify} className="space-y-5">
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
      <ErrorText error={verifyOtp.error} />
      <Button type="submit" className="w-full py-3" loading={verifyOtp.isPending}>
        {t("login.verify")}
      </Button>
      <Button
        type="button"
        variant="ghost"
        className="w-full"
        onClick={() => {
          setCodeSent(false);
          setCode("");
        }}
      >
        <ArrowLeft className="h-4 w-4" aria-hidden />
        {t("login.changeNumber")}
      </Button>
    </form>
  );
}

function GoogleIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden>
      <path fill="#4285F4" d="M23.5 12.3c0-.8-.1-1.6-.2-2.3H12v4.5h6.5a5.6 5.6 0 0 1-2.4 3.6v3h3.9c2.3-2.1 3.5-5.2 3.5-8.8z" />
      <path fill="#34A853" d="M12 24c3.2 0 6-1.1 8-2.9l-3.9-3c-1.1.7-2.5 1.2-4.1 1.2-3.1 0-5.8-2.1-6.7-5H1.3v3.1A12 12 0 0 0 12 24z" />
      <path fill="#FBBC05" d="M5.3 14.3a7.2 7.2 0 0 1 0-4.6V6.6h-4a12 12 0 0 0 0 10.8z" />
      <path fill="#EA4335" d="M12 4.8c1.8 0 3.3.6 4.6 1.8l3.4-3.4A12 12 0 0 0 1.3 6.6l4 3.1c.9-2.9 3.6-4.9 6.7-4.9z" />
    </svg>
  );
}

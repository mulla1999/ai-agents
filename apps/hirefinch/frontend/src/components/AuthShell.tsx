// Split-screen layout shared by every public page (sign in, register, reset, privacy).

import { ArrowRight, Bird, Eye, EyeOff, FileCheck2, Info, Radar, ShieldCheck } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router";
import { api } from "../api/client";
import { cx } from "./ui";
import { BRAND, TAGLINE } from "../brand";

const FEATURES = [
  { icon: Radar, title: "Finds roles that fit", text: "Scans company job boards and scores every role against your verified resume." },
  { icon: FileCheck2, title: "Tailors every resume", text: "Reorders your real experience for each job, then fact-checks it. Nothing invented." },
  { icon: ShieldCheck, title: "You stay in control", text: "Applications and emails wait for your approval. Every action is audited." },
];

export function Logo({ light = false }: { light?: boolean }) {
  return (
    <Link to="/" className="flex items-center gap-2.5">
      <span
        className={cx(
          "grid size-9 place-items-center rounded-xl shadow-sm",
          light ? "bg-white/15 ring-1 ring-white/30" : "bg-gradient-to-br from-indigo-600 to-violet-600",
        )}
      >
        <Bird className="size-5 text-white" aria-hidden />
      </span>
      <span className={cx("text-lg font-semibold tracking-tight", light ? "text-white" : "text-slate-900")}>{BRAND}</span>
    </Link>
  );
}

export function AuthShell({ badge, title, subtitle, children }: { badge?: ReactNode; title: string; subtitle?: ReactNode; children: ReactNode }) {
  return (
    <div className="min-h-screen bg-white lg:grid lg:h-screen lg:grid-cols-[1.1fr_1fr] lg:overflow-hidden">
      <section className="relative hidden overflow-hidden bg-gradient-to-br from-indigo-700 via-indigo-600 to-violet-600 lg:flex lg:flex-col lg:justify-between lg:gap-6 lg:px-12 lg:py-10">
        <div aria-hidden className="pointer-events-none absolute -left-24 -top-24 size-96 rounded-full bg-violet-400/30 blur-3xl" />
        <div aria-hidden className="pointer-events-none absolute -bottom-32 right-0 size-[28rem] rounded-full bg-indigo-300/20 blur-3xl" />
        <div className="relative">
          <Logo light />
        </div>
        <div className="relative mx-auto w-full max-w-xl">
          <h1 className="text-3xl font-semibold leading-tight tracking-tight text-white xl:text-4xl">
            Your job search on autopilot,
            <span className="block text-indigo-200">with you in control.</span>
          </h1>
          <p className="mt-3 max-w-md text-[15px] text-indigo-100/90">
            Discover matching roles, send a tailored resume for each one, and track every application in one place.
          </p>
          <img
            src="/login-hero.svg"
            alt="A matched job card, a validated tailored resume and an approval step"
            className="login-float mx-auto mt-6 max-h-[42vh] w-full max-w-md object-contain drop-shadow-2xl"
          />
        </div>
        {/* Hidden on short screens so the panel never overflows. */}
        <ul className="relative grid grid-cols-3 gap-3 [@media(max-height:760px)]:hidden">
          {FEATURES.map(({ icon: Icon, title, text }) => (
            <li key={title} className="rounded-2xl bg-white/10 p-3.5 ring-1 ring-white/15 backdrop-blur-sm">
              <Icon className="size-5 text-indigo-100" aria-hidden />
              <p className="mt-2 text-sm font-semibold text-white">{title}</p>
              <p className="mt-1 text-xs leading-relaxed text-indigo-100/80">{text}</p>
            </li>
          ))}
        </ul>
      </section>

      <section className="flex min-h-screen flex-col justify-between px-6 py-8 sm:px-12 lg:min-h-0 lg:overflow-y-auto">
        <div className="lg:hidden">
          <Logo />
        </div>
        <div className="mx-auto w-full max-w-sm py-10">
          {badge}
          <h2 className="mt-5 text-3xl font-semibold tracking-tight text-slate-900">{title}</h2>
          {subtitle && <p className="mt-2 text-sm text-slate-500">{subtitle}</p>}
          <div className="mt-8">{children}</div>
        </div>
        <p className="text-center text-xs text-slate-400">
          {BRAND} · {TAGLINE.toLowerCase()} ·{" "}
          <Link to="/privacy" className="hover:text-slate-600 hover:underline">
            Privacy
          </Link>
        </p>
      </section>
    </div>
  );
}

const inputBase =
  "block w-full rounded-xl border bg-white py-3 px-3.5 text-sm text-slate-900 shadow-sm outline-none transition placeholder:text-slate-400 focus:border-indigo-500 focus:ring-4 focus:ring-indigo-500/15";

export function AuthInput({
  label,
  hint,
  invalid,
  ...props
}: React.InputHTMLAttributes<HTMLInputElement> & { label: string; hint?: ReactNode; invalid?: boolean }) {
  const [visible, setVisible] = useState(false);
  const isPassword = props.type === "password";
  const id = props.id ?? props.name;
  return (
    <div>
      <label htmlFor={id} className="block text-sm font-medium text-slate-700">
        {label}
      </label>
      <div className="relative mt-1.5">
        <input
          {...props}
          id={id}
          type={isPassword && visible ? "text" : props.type}
          aria-invalid={invalid}
          className={cx(inputBase, isPassword && "pr-11", invalid ? "border-rose-300" : "border-slate-300")}
        />
        {isPassword && (
          <button
            type="button"
            onClick={() => setVisible(!visible)}
            aria-label={visible ? "Hide password" : "Show password"}
            className="absolute right-2 top-1/2 -translate-y-1/2 rounded-lg p-1.5 text-slate-400 transition hover:bg-slate-100 hover:text-slate-600"
          >
            {visible ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
          </button>
        )}
      </div>
      {hint && <p className="mt-1.5 text-xs text-slate-500">{hint}</p>}
    </div>
  );
}

export function SubmitButton({ busy, disabled, children }: { busy?: boolean; disabled?: boolean; children: ReactNode }) {
  return (
    <button
      type="submit"
      disabled={busy || disabled}
      className={cx(
        "group flex w-full items-center justify-center gap-2 rounded-xl px-4 py-3 text-sm font-semibold text-white shadow-lg shadow-indigo-600/25 transition",
        "bg-gradient-to-r from-indigo-600 to-violet-600 hover:from-indigo-500 hover:to-violet-500",
        "focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-indigo-500/30 disabled:cursor-not-allowed disabled:opacity-60",
      )}
    >
      {busy ? "Please wait…" : children}
      {!busy && <ArrowRight className="size-4 transition group-hover:translate-x-0.5" aria-hidden />}
    </button>
  );
}

export function FormError({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <p role="alert" className="rounded-xl bg-rose-50 px-3.5 py-2.5 text-sm text-rose-700 ring-1 ring-rose-100">
      {message}
    </p>
  );
}

export function FormSuccess({ children }: { children: ReactNode }) {
  return (
    <div role="status" className="flex items-start gap-3 rounded-xl bg-emerald-50 p-4 text-sm text-emerald-800 ring-1 ring-emerald-100">
      <ShieldCheck className="mt-0.5 size-5 shrink-0" aria-hidden />
      <div>{children}</div>
    </div>
  );
}

/** Shown only in development, when no platform email is configured and the API returns the link. */
export function DevLink({ link }: { link?: string | null }) {
  if (!link) return null;
  return (
    <div className="mt-4 flex items-start gap-3 rounded-xl bg-sky-50 p-4 text-sm text-sky-900 ring-1 ring-sky-100">
      <Info className="mt-0.5 size-5 shrink-0" aria-hidden />
      <div className="min-w-0">
        <p className="font-medium">Development: no platform email is configured</p>
        <p className="mt-1 text-xs">The link that would have been emailed:</p>
        <a href={link} className="mt-1 block break-all text-xs font-medium text-indigo-700 underline">
          {link}
        </a>
      </div>
    </div>
  );
}

export function AuthLink({ to, children }: { to: string; children: ReactNode }) {
  return (
    <Link to={to} className="font-medium text-indigo-700 hover:text-indigo-600 hover:underline">
      {children}
    </Link>
  );
}

export function AuthButtonLink({ to, children }: { to: string; children: ReactNode }) {
  return (
    <Link
      to={to}
      className="group flex w-full items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-indigo-600 to-violet-600 px-4 py-3 text-sm font-semibold text-white shadow-lg shadow-indigo-600/25 transition hover:from-indigo-500 hover:to-violet-500 focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-indigo-500/30"
    >
      {children}
      <ArrowRight className="size-4 transition group-hover:translate-x-0.5" aria-hidden />
    </Link>
  );
}

/** "Continue with Google": a full-page navigation, shown only when the platform enabled it. */
export function GoogleButton({ label = "Continue with Google" }: { label?: string }) {
  const [enabled, setEnabled] = useState(false);
  useEffect(() => {
    let live = true;
    api<{ enabled: boolean }>("/auth/google/config")
      .then((r) => live && setEnabled(r.enabled))
      .catch(() => live && setEnabled(false));
    return () => {
      live = false;
    };
  }, []);
  if (!enabled) return null;
  return (
    <div className="mt-6">
      <div className="relative my-5 text-center text-xs uppercase tracking-wide text-slate-400">
        <span className="relative z-10 bg-white px-3">or</span>
        <span aria-hidden className="absolute left-0 right-0 top-1/2 h-px bg-slate-200" />
      </div>
      <button
        type="button"
        onClick={() => {
          window.location.href = "/api/auth/google/start";
        }}
        className="flex w-full items-center justify-center gap-3 rounded-xl border border-slate-300 bg-white px-4 py-3 text-sm font-semibold text-slate-700 shadow-sm transition hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-indigo-500/20"
      >
        <svg viewBox="0 0 48 48" className="size-5" aria-hidden>
          <path fill="#FFC107" d="M43.6 20.5H42V20H24v8h11.3C33.7 32.7 29.2 36 24 36c-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.8 1.2 7.9 3l5.7-5.7C34 6.1 29.3 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.3-.1-2.4-.4-3.5z" />
          <path fill="#FF3D00" d="M6.3 14.7l6.6 4.8C14.7 15.1 19 12 24 12c3.1 0 5.8 1.2 7.9 3l5.7-5.7C34 6.1 29.3 4 24 4 16.3 4 9.7 8.3 6.3 14.7z" />
          <path fill="#4CAF50" d="M24 44c5.2 0 9.9-2 13.4-5.2l-6.2-5.2C29.2 35.1 26.7 36 24 36c-5.2 0-9.6-3.3-11.3-8l-6.5 5C9.5 39.6 16.2 44 24 44z" />
          <path fill="#1976D2" d="M43.6 20.5H42V20H24v8h11.3c-.8 2.2-2.2 4.2-4.1 5.6l6.2 5.2C37 39.2 44 34 44 24c0-1.3-.1-2.4-.4-3.5z" />
        </svg>
        {label}
      </button>
    </div>
  );
}

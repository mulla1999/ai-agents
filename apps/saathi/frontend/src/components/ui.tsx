import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode, SelectHTMLAttributes, TextareaHTMLAttributes } from "react";
import type { LucideIcon } from "lucide-react";
import { AlertCircle, Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";

const cx = (...classes: (string | false | null | undefined)[]) => classes.filter(Boolean).join(" ");

type Variant = "primary" | "secondary" | "danger" | "ghost" | "accent";
const variants: Record<Variant, string> = {
  primary: "bg-brand-700 text-white shadow-sm hover:bg-brand-800 disabled:bg-stone-300 disabled:shadow-none",
  accent: "bg-saffron-500 text-white shadow-sm hover:bg-saffron-600 disabled:bg-stone-300",
  secondary: "bg-white text-stone-800 ring-1 ring-stone-200 shadow-sm hover:bg-stone-50 hover:ring-stone-300 disabled:text-stone-400",
  danger: "bg-red-600 text-white shadow-sm hover:bg-red-700 disabled:bg-stone-300",
  ghost: "text-brand-700 hover:bg-brand-50",
};

export function Button({
  variant = "primary",
  className,
  loading,
  children,
  disabled,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; loading?: boolean }) {
  return (
    <button
      className={cx(
        "inline-flex items-center justify-center gap-2 rounded-xl px-4 py-2.5 text-sm font-semibold transition-all focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-brand-200 active:scale-[0.98] disabled:cursor-not-allowed",
        variants[variant],
        className,
      )}
      disabled={disabled || loading}
      {...props}
    >
      {loading && <Loader2 className="h-4 w-4 animate-spin" aria-hidden />}
      {children}
    </button>
  );
}

export function Card({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cx("rounded-2xl bg-white p-5 shadow-card ring-1 ring-stone-200/70 sm:p-6", className)}>{children}</div>;
}

export function PageHeader({ title, subtitle, icon: Icon, action }: { title: string; subtitle?: string; icon?: LucideIcon; action?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-4">
      <div className="flex items-center gap-3">
        {Icon && (
          <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-brand-100 text-brand-700">
            <Icon className="h-5 w-5" aria-hidden />
          </span>
        )}
        <div>
          <h1 className="text-xl font-bold tracking-tight text-brand-950 sm:text-2xl">{title}</h1>
          {subtitle && <p className="text-sm text-stone-600">{subtitle}</p>}
        </div>
      </div>
      {action}
    </div>
  );
}

/** A labelled form control. Use ``group`` for button groups: a <label> may only wrap one control. */
export function Field({ label, hint, children, group = false }: { label: string; hint?: string; children: ReactNode; group?: boolean }) {
  const content = (
    <>
      <span className="block text-sm font-medium text-stone-700">{label}</span>
      {children}
      {hint && <span className="block text-xs text-stone-500">{hint}</span>}
    </>
  );
  return group ? (
    <div role="group" aria-label={label} className="space-y-1.5">
      {content}
    </div>
  ) : (
    <label className="block space-y-1.5">{content}</label>
  );
}

const inputClass =
  "w-full rounded-xl border border-stone-200 bg-white px-3.5 py-2.5 text-sm shadow-sm transition placeholder:text-stone-400 focus:border-brand-500 focus:outline-none focus:ring-4 focus:ring-brand-100 disabled:bg-stone-50";

export const Input = ({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) => (
  <input className={cx(inputClass, className)} {...props} />
);
export const Select = ({ className, ...props }: SelectHTMLAttributes<HTMLSelectElement>) => (
  <select className={cx(inputClass, className)} {...props} />
);
export const Textarea = ({ className, ...props }: TextareaHTMLAttributes<HTMLTextAreaElement>) => (
  <textarea className={cx(inputClass, className)} {...props} />
);

const tones = {
  green: "bg-emerald-50 text-emerald-700 ring-emerald-600/20",
  amber: "bg-saffron-50 text-saffron-600 ring-saffron-500/25",
  red: "bg-red-50 text-red-700 ring-red-600/20",
  stone: "bg-stone-100 text-stone-700 ring-stone-500/20",
  blue: "bg-sky-50 text-sky-700 ring-sky-600/20",
  brand: "bg-brand-50 text-brand-700 ring-brand-600/20",
};

export function Badge({ tone = "stone", children, icon: Icon }: { tone?: keyof typeof tones; children: ReactNode; icon?: LucideIcon }) {
  return (
    <span className={cx("inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-semibold ring-1 ring-inset", tones[tone])}>
      {Icon && <Icon className="h-3.5 w-3.5" aria-hidden />}
      {children}
    </span>
  );
}

export function Spinner() {
  const { t } = useTranslation();
  return (
    <div className="flex items-center justify-center gap-2 py-12 text-sm text-stone-500" role="status">
      <Loader2 className="h-5 w-5 animate-spin text-brand-600" aria-hidden />
      {t("common.loading")}
    </div>
  );
}

export function EmptyState({ icon: Icon, title, children }: { icon: LucideIcon; title: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center rounded-2xl border border-dashed border-stone-300 bg-white/60 px-6 py-12 text-center">
      <span className="mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-brand-50 text-brand-600">
        <Icon className="h-7 w-7" aria-hidden />
      </span>
      <p className="font-semibold text-stone-800">{title}</p>
      {children && <div className="mt-1 max-w-sm text-sm text-stone-600">{children}</div>}
    </div>
  );
}

export function ErrorText({ error }: { error: unknown }) {
  const { t } = useTranslation();
  if (!error) return null;
  const message = error instanceof Error ? error.message : t("common.error");
  return (
    <p role="alert" className="flex items-start gap-2 rounded-xl bg-red-50 px-3.5 py-2.5 text-sm text-red-700 ring-1 ring-inset ring-red-600/10">
      <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
      {message}
    </p>
  );
}

export function Notice({ tone = "amber", icon: Icon, children }: { tone?: "amber" | "green" | "blue"; icon?: LucideIcon; children: ReactNode }) {
  const styles = {
    amber: "bg-saffron-50 text-saffron-600 ring-saffron-500/20",
    green: "bg-emerald-50 text-emerald-800 ring-emerald-600/15",
    blue: "bg-sky-50 text-sky-800 ring-sky-600/15",
  };
  return (
    <div className={cx("flex items-start gap-2.5 rounded-xl px-4 py-3 text-sm ring-1 ring-inset", styles[tone])}>
      {Icon && <Icon className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />}
      <div>{children}</div>
    </div>
  );
}

export function Initials({ name, className }: { name: string; className?: string }) {
  const initials = name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join("");
  return (
    <span className={cx("flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-brand-400 to-brand-700 text-sm font-bold text-white", className)}>
      {initials || "?"}
    </span>
  );
}

export function formatDate(value: string | null | undefined, lang: string): string {
  if (!value) return "—";
  return new Date(value).toLocaleString(lang === "hi" ? "hi-IN" : "en-IN", { dateStyle: "medium", timeStyle: "short" });
}

export { cx };

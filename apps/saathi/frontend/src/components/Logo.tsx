import { useId } from "react";
import { useTranslation } from "react-i18next";
import { cx } from "./ui";

/** Saathi mark: two companions walking together under a protective arc, with a saffron spark of hope. */
export function LogoMark({ className = "h-9 w-9" }: { className?: string }) {
  const id = useId();
  return (
    <svg viewBox="0 0 48 48" className={className} role="img" aria-label="Saathi">
      <defs>
        <linearGradient id={`${id}-bg`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#2a947f" />
          <stop offset="1" stopColor="#133f39" />
        </linearGradient>
      </defs>
      <rect width="48" height="48" rx="14" fill={`url(#${id}-bg)`} />
      {/* protective arc */}
      <path d="M10 27a14 14 0 0 1 28 0" fill="none" stroke="#afe3d5" strokeWidth="2.6" strokeLinecap="round" opacity="0.9" />
      {/* companion (taller) */}
      <circle cx="19.5" cy="23" r="3.4" fill="#fff" />
      <path d="M13.5 38.5c0-5 2.6-9.2 6-9.2s6 4.2 6 9.2" fill="#fff" />
      {/* person being helped */}
      <circle cx="29.5" cy="25.6" r="2.9" fill="#fff" opacity="0.92" />
      <path d="M24.6 38.5c0-4.2 2.2-7.6 4.9-7.6s4.9 3.4 4.9 7.6" fill="#fff" opacity="0.92" />
      {/* hope spark */}
      <path d="M36 9.5l1.3 3.2 3.2 1.3-3.2 1.3-1.3 3.2-1.3-3.2-3.2-1.3 3.2-1.3z" fill="#fbab2b" />
    </svg>
  );
}

export function Logo({ className, light = false }: { className?: string; light?: boolean }) {
  const { t } = useTranslation();
  return (
    <span className={cx("inline-flex items-center gap-2.5", className)}>
      <LogoMark />
      <span className="flex flex-col leading-none">
        <span className={cx("text-xl font-bold tracking-tight", light ? "text-white" : "text-brand-900")}>{t("app.name")}</span>
        <span className={cx("mt-0.5 text-[11px] font-medium", light ? "text-brand-100" : "text-brand-600")}>{t("app.short")}</span>
      </span>
    </span>
  );
}

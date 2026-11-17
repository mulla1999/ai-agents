import { Globe } from "lucide-react";
import { useTranslation } from "react-i18next";
import { LANGUAGES, setLanguage } from "../i18n";
import { cx } from "./ui";

/** Segmented EN / हिंदी switch. */
export function LanguageSwitch({ dark = false }: { dark?: boolean }) {
  const { i18n } = useTranslation();
  return (
    <div
      role="group"
      aria-label="Language"
      className={cx("inline-flex items-center gap-1 rounded-full p-1 text-xs font-semibold", dark ? "bg-white/10" : "bg-white shadow-sm ring-1 ring-stone-200")}
    >
      <Globe className={cx("ml-1.5 h-3.5 w-3.5", dark ? "text-brand-100" : "text-stone-400")} aria-hidden />
      {LANGUAGES.map((l) => (
        <button
          key={l.code}
          type="button"
          aria-pressed={i18n.language === l.code}
          onClick={() => setLanguage(l.code)}
          className={cx(
            "rounded-full px-3 py-1 transition",
            i18n.language === l.code
              ? dark
                ? "bg-white text-brand-800 shadow-sm"
                : "bg-brand-700 text-white shadow-sm"
              : dark
                ? "text-brand-100 hover:text-white"
                : "text-stone-600 hover:text-stone-900",
          )}
        >
          {l.label}
        </button>
      ))}
    </div>
  );
}

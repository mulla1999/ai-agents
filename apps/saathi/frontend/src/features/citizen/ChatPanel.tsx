import { Mic, SendHorizontal } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { ApiError } from "../../api/client";
import { useMessages, useSendMessage } from "../../api/hooks";
import type { Citizen } from "../../api/types";
import { LogoMark } from "../../components/Logo";
import { cx, ErrorText, Notice, Spinner } from "../../components/ui";

export function ChatPanel({ citizen }: { citizen: Citizen }) {
  const { t } = useTranslation();
  const messages = useMessages(citizen.id);
  const send = useSendMessage(citizen.id);
  const [draft, setDraft] = useState("");
  const [pending, setPending] = useState<string | null>(null);
  const bottom = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages.data, pending]);

  const submit = (text: string) => {
    const message = text.trim();
    if (!message || send.isPending) return;
    setPending(message);
    setDraft("");
    send.mutate(message, { onSettled: () => setPending(null) });
  };
  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    submit(draft);
  };

  if (messages.isPending) return <Spinner />;
  const unavailable = send.error instanceof ApiError && send.error.status === 503;
  const empty = messages.data?.length === 0 && !pending;
  const suggestions = [t("chat.suggest1"), t("chat.suggest2"), t("chat.suggest3"), t("chat.suggest4")];

  return (
    <div className="flex h-[68vh] min-h-[480px] flex-col overflow-hidden rounded-3xl bg-white shadow-card ring-1 ring-stone-200/70">
      <div className="flex items-center gap-3 border-b border-stone-100 px-5 py-3.5">
        <LogoMark className="h-9 w-9" />
        <div>
          <p className="text-sm font-semibold text-brand-950">{t("app.name")}</p>
          <p className="flex items-center gap-1.5 text-xs text-stone-500">
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
            {t("chat.status")}
          </p>
        </div>
      </div>

      <div className="flex-1 space-y-4 overflow-y-auto bg-gradient-to-b from-brand-50/40 to-white px-4 py-5 sm:px-6" aria-live="polite">
        {empty && (
          <div className="flex h-full flex-col items-center justify-center text-center">
            <LogoMark className="h-16 w-16 animate-float" />
            <p className="mt-4 text-lg font-semibold text-brand-950">{t("chat.welcomeTitle")}</p>
            <p className="mt-1 max-w-sm text-sm text-stone-600">{t("chat.empty")}</p>
            <div className="mt-6 flex max-w-lg flex-wrap justify-center gap-2">
              {suggestions.map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => submit(s)}
                  className="rounded-full bg-white px-4 py-2 text-sm text-brand-800 shadow-sm ring-1 ring-brand-200 transition hover:bg-brand-50 hover:ring-brand-300"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}
        {messages.data?.map((m, i) => (
          <Bubble key={i} mine={m.role === "user"} text={m.content} />
        ))}
        {pending && (
          <>
            <Bubble mine text={pending} />
            <div className="flex items-end gap-2">
              <LogoMark className="h-7 w-7" />
              <div className="flex gap-1 rounded-2xl rounded-bl-md bg-white px-4 py-3 shadow-sm ring-1 ring-stone-200/70" aria-label={t("chat.thinking")}>
                {[0, 1, 2].map((dot) => (
                  <span key={dot} className={cx("h-2 w-2 animate-bounce rounded-full bg-brand-400", dot === 1 && "[animation-delay:150ms]", dot === 2 && "[animation-delay:300ms]")} />
                ))}
              </div>
            </div>
          </>
        )}
        <div ref={bottom} />
      </div>

      {unavailable ? (
        <div className="border-t border-stone-100 p-4">
          <Notice tone="amber">{t("chat.unavailable")}</Notice>
        </div>
      ) : (
        send.error && (
          <div className="px-4 pt-3">
            <ErrorText error={send.error} />
          </div>
        )
      )}
      <form onSubmit={onSubmit} className="flex items-center gap-2 border-t border-stone-100 bg-white p-3 sm:p-4">
        <input
          className="flex-1 rounded-full border border-stone-200 bg-stone-50 px-5 py-3 text-sm transition focus:border-brand-500 focus:bg-white focus:outline-none focus:ring-4 focus:ring-brand-100"
          value={draft}
          maxLength={2000}
          onChange={(e) => setDraft(e.target.value)}
          placeholder={t("chat.placeholder")}
          aria-label={t("chat.placeholder")}
        />
        <span className="hidden text-stone-300 sm:block" title={t("chat.voiceHint")}>
          <Mic className="h-5 w-5" aria-hidden />
        </span>
        <button
          type="submit"
          disabled={!draft.trim() || send.isPending}
          aria-label={t("chat.send")}
          className="flex h-11 w-11 items-center justify-center rounded-full bg-brand-700 text-white shadow-sm transition hover:bg-brand-800 disabled:bg-stone-300"
        >
          <SendHorizontal className="h-5 w-5" aria-hidden />
        </button>
      </form>
    </div>
  );
}

function Bubble({ mine, text }: { mine: boolean; text: string }) {
  if (mine) {
    return (
      <div className="flex justify-end animate-fade-up">
        <p className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-md bg-brand-700 px-4 py-2.5 text-sm text-white shadow-sm">{text}</p>
      </div>
    );
  }
  return (
    <div className="flex items-end gap-2 animate-fade-up">
      <LogoMark className="h-7 w-7 shrink-0" />
      <p className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-bl-md bg-white px-4 py-2.5 text-sm leading-relaxed text-stone-800 shadow-sm ring-1 ring-stone-200/70">
        {text}
      </p>
    </div>
  );
}

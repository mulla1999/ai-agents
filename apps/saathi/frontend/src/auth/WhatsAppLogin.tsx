import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";
import { keys } from "../api/hooks";
import type { User } from "../api/types";
import { Button, ErrorText } from "../components/ui";

interface Started {
  code: string;
  link: string;
  expires_in_seconds: number;
}

/** "Sign in with WhatsApp": show a code, the person sends it to the bot, we poll until it arrives. */
export function WhatsAppLogin({ onSignedIn }: { onSignedIn: (user: User) => void }) {
  const { t } = useTranslation();
  const client = useQueryClient();
  const [started, setStarted] = useState<Started | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [secondsLeft, setSecondsLeft] = useState(0);
  // Kept in a ref so a new callback from the parent does not restart polling.
  const onSignedInRef = useRef(onSignedIn);
  onSignedInRef.current = onSignedIn;

  const start = async () => {
    setError(null);
    try {
      const s = await api<Started>("/auth/whatsapp/start", { method: "POST" });
      setStarted(s);
      setSecondsLeft(s.expires_in_seconds);
    } catch (e) {
      setError(e);
    }
  };

  useEffect(() => {
    if (!started) return;
    let stopped = false;
    const tick = setInterval(() => setSecondsLeft((s) => Math.max(0, s - 1)), 1000);
    const poll = setInterval(async () => {
      try {
        const result = await api<{ status: string; user: User | null }>("/auth/whatsapp/poll", { method: "POST" });
        if (!stopped && result.status === "signed_in" && result.user) {
          stopped = true;
          client.setQueryData(keys.me, result.user);
          onSignedInRef.current(result.user);
        }
      } catch (e) {
        stopped = true;
        setError(e);
        setStarted(null);
      }
    }, 2500);
    return () => {
      stopped = true;
      clearInterval(tick);
      clearInterval(poll);
    };
  }, [started, client]);

  if (!started) {
    return (
      <div className="space-y-2">
        <Button type="button" variant="secondary" className="w-full" onClick={start}>
          {t("login.whatsapp")}
        </Button>
        <ErrorText error={error} />
      </div>
    );
  }

  return (
    <div className="space-y-3 rounded-lg bg-green-50 p-4 text-sm">
      <p>{t("login.whatsappStep")}</p>
      <p className="text-center font-mono text-2xl tracking-widest">LOGIN {started.code}</p>
      <a
        href={started.link}
        target="_blank"
        rel="noopener noreferrer"
        className="flex w-full items-center justify-center rounded-lg bg-green-600 px-4 py-2 font-medium text-white hover:bg-green-700"
      >
        {t("login.openWhatsapp")}
      </a>
      <p className="text-center text-stone-600">
        {secondsLeft > 0 ? t("login.waiting", { seconds: secondsLeft }) : t("login.codeExpired")}
      </p>
      {secondsLeft === 0 && (
        <Button type="button" variant="ghost" className="w-full" onClick={start}>
          {t("login.tryAgain")}
        </Button>
      )}
    </div>
  );
}

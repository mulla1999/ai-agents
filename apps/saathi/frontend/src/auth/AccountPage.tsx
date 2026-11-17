import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router";
import { api } from "../api/client";
import { keys, useAuthConfig, useRequestOtp } from "../api/hooks";
import type { User } from "../api/types";
import { Badge, Button, Card, ErrorText, Field, Input } from "../components/ui";
import { useAuth } from "./AuthContext";

export function AccountPage() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const config = useAuthConfig();
  const [params] = useSearchParams();
  if (!user) return null;
  const methods = user.sign_in_methods ?? [];

  return (
    <div className="max-w-2xl space-y-4">
      <h1 className="text-xl font-semibold">{t("account.title")}</h1>
      {params.get("linked") === "google" && <p className="rounded-lg bg-green-50 px-3 py-2 text-sm text-green-800">{t("account.googleLinked")}</p>}
      {params.get("error") === "google_in_use" && <ErrorText error={new Error(t("account.googleInUse"))} />}

      <Card className="space-y-2">
        <p className="font-medium">{user.display_name ?? "—"}</p>
        {user.email && <p className="text-sm text-stone-600">{user.email}</p>}
        {user.phone && <p className="text-sm text-stone-600">{user.phone}</p>}
        <p className="text-sm">
          {t("admin.role")}: {t(`roles.${user.role}`)}
        </p>
        <div className="flex gap-2">
          {methods.map((m) => (
            <Badge key={m} tone="green">
              {t(`account.method.${m}`)}
            </Badge>
          ))}
        </div>
      </Card>

      {!methods.includes("phone") && <AddPhone />}

      {config.data?.google_enabled && !methods.includes("google") && (
        <Card className="space-y-2">
          <h2 className="font-semibold">{t("account.linkGoogle")}</h2>
          <p className="text-sm text-stone-600">{t("account.linkGoogleHint")}</p>
          <a
            href="/api/auth/google/login?link=true&next=/account"
            className="inline-flex rounded-lg bg-white px-4 py-2 text-sm font-medium ring-1 ring-stone-300 hover:bg-stone-100"
          >
            {t("login.google")}
          </a>
        </Card>
      )}
    </div>
  );
}

function AddPhone() {
  const { t } = useTranslation();
  const client = useQueryClient();
  const request = useRequestOtp();
  const link = useMutation({
    mutationFn: (body: { phone: string; code: string }) => api<User>("/auth/link/phone", { method: "POST", body }),
    onSuccess: (user) => client.setQueryData(keys.me, user),
  });
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [sent, setSent] = useState(false);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!sent) request.mutate(phone, { onSuccess: () => setSent(true) });
    else link.mutate({ phone, code });
  };

  return (
    <Card>
      <form onSubmit={submit} className="space-y-3">
        <h2 className="font-semibold">{t("account.addPhone")}</h2>
        <p className="text-sm text-stone-600">{t("account.addPhoneHint")}</p>
        <Field label={t("login.phone")} hint={t("login.phoneHint")}>
          <Input type="tel" required disabled={sent} value={phone} onChange={(e) => setPhone(e.target.value)} />
        </Field>
        {sent && (
          <Field label={t("login.code")}>
            <Input inputMode="numeric" autoComplete="one-time-code" pattern="\d{6}" maxLength={6} required value={code} onChange={(e) => setCode(e.target.value)} />
          </Field>
        )}
        <ErrorText error={request.error ?? link.error} />
        <Button type="submit" disabled={request.isPending || link.isPending}>
          {sent ? t("account.confirm") : t("login.sendCode")}
        </Button>
      </form>
    </Card>
  );
}

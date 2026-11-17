import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api/client";
import type { TwoFactorSetup } from "../api/types";
import { useMe } from "../auth";
import { ExtensionKeys } from "../components/ExtensionKeys";
import { Alert, Badge, Button, Card, ErrorText, Field, PageHeader, TextInput, formatDate, useAction } from "../components/ui";
import { BRAND } from "../brand";

const ROLE_TONE = { superadmin: "indigo", admin: "blue", user: "slate" } as const;
const ROLE_LABEL: Record<string, string> = { superadmin: "Owner (admin)", admin: "Admin", user: "Member" };

export function AccountPage() {
  const me = useMe();
  return (
    <>
      <PageHeader title="Account" subtitle="Your sign-in details and account controls." />
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Your account">
          <dl className="grid grid-cols-[8rem_1fr] gap-y-2 text-sm">
            <dt className="text-slate-500">Name</dt>
            <dd>{me.full_name || "—"}</dd>
            <dt className="text-slate-500">Email</dt>
            <dd className="break-all">{me.email}</dd>
            <dt className="text-slate-500">Role</dt>
            <dd>
              <Badge tone={ROLE_TONE[me.role]}>{ROLE_LABEL[me.role] ?? me.role}</Badge>
            </dd>
            <dt className="text-slate-500">Member since</dt>
            <dd>{formatDate(me.created_at)}</dd>
            <dt className="text-slate-500">Last sign-in</dt>
            <dd>{formatDate(me.last_login_at, true)}</dd>
            <dt className="text-slate-500">Sign-in</dt>
            <dd className="flex flex-wrap gap-1.5">
              <Badge tone={me.two_factor ? "green" : "slate"}>{me.two_factor ? "Password + 2-step code" : "Password (2-step off)"}</Badge>
              {me.google_linked && <Badge tone="blue">Google linked</Badge>}
            </dd>
          </dl>
        </Card>
        <TwoFactor enabled={!!me.two_factor} codesLeft={me.recovery_codes_left ?? 0} email={me.email} />
        <ChangePassword />
        <ExtensionKeys />
        <DeleteAccount isSuperadmin={me.role === "superadmin"} />
      </div>
    </>
  );
}

function TwoFactor({ enabled, codesLeft, email }: { enabled: boolean; codesLeft: number; email: string }) {
  const [setup, setSetup] = useState<TwoFactorSetup | null>(null);
  const [code, setCode] = useState("");
  const [codes, setCodes] = useState<string[] | null>(null);
  const [password, setPassword] = useState("");
  const [offCode, setOffCode] = useState("");
  const start = useAction(() => api<TwoFactorSetup>("/auth/2fa/setup", { method: "POST" }), setSetup);
  const enable = useAction(
    () => api<{ enabled: boolean; recovery_codes: string[] }>("/auth/2fa/enable", { method: "POST", body: { code: code.trim() } }),
    (r) => {
      setCodes(r.recovery_codes);
      setSetup(null);
      setCode("");
    },
  );
  const disable = useAction(() => api("/auth/2fa/disable", { method: "POST", body: { password, code: offCode.trim() } }), () => {
    setPassword("");
    setOffCode("");
  });

  if (codes) {
    const text = codes.join("\n");
    return (
      <Card title="Two-factor sign-in is on">
        <div className="space-y-3">
          <Alert tone="warning">
            Save these recovery codes now; they are shown only once. Each works once if you lose your phone.
          </Alert>
          <ul className="grid grid-cols-2 gap-1.5 rounded-lg bg-slate-50 p-3 font-mono text-sm" aria-label="Recovery codes">
            {codes.map((c) => (
              <li key={c}>{c}</li>
            ))}
          </ul>
          <div className="flex flex-wrap gap-2">
            <Button onClick={() => navigator.clipboard?.writeText(text)}>Copy</Button>
            <Button
              onClick={() => {
                const url = URL.createObjectURL(new Blob([`${BRAND} recovery codes for ${email}\n\n${text}\n`], { type: "text/plain" }));
                const a = document.createElement("a");
                a.href = url;
                a.download = "hirefinch-recovery-codes.txt";
                a.click();
                URL.revokeObjectURL(url);
              }}
            >
              Download .txt
            </Button>
            <Button variant="primary" onClick={() => setCodes(null)}>
              I saved them
            </Button>
          </div>
        </div>
      </Card>
    );
  }

  if (enabled) {
    return (
      <Card title="Two-factor sign-in">
        <form
          className="space-y-3"
          onSubmit={(e) => {
            e.preventDefault();
            disable.mutate();
          }}
        >
          <p className="text-sm text-slate-600">
            On. Each sign-in asks for a code from your authenticator app. Recovery codes left: <strong>{codesLeft}</strong>
            {codesLeft <= 3 && " (turn two-factor off and on again for a fresh set)"}.
          </p>
          <div className="grid gap-3 md:grid-cols-2">
            <Field label="Password">
              <TextInput type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
            </Field>
            <Field label="Code or recovery code">
              <TextInput autoComplete="one-time-code" value={offCode} onChange={(e) => setOffCode(e.target.value)} />
            </Field>
          </div>
          <ErrorText error={disable.error} />
          <Button type="submit" variant="danger" busy={disable.isPending} disabled={!password || offCode.trim().length < 6}>
            Turn off two-factor
          </Button>
        </form>
      </Card>
    );
  }

  return (
    <Card title="Two-factor sign-in">
      {!setup ? (
        <div className="space-y-3">
          <p className="text-sm text-slate-600">
            Add a second step at sign-in with an authenticator app (Google Authenticator, Microsoft Authenticator, 1Password, Authy).
          </p>
          <ErrorText error={start.error} />
          <Button variant="primary" busy={start.isPending} onClick={() => start.mutate()}>
            Turn on
          </Button>
        </div>
      ) : (
        <form
          className="space-y-3"
          onSubmit={(e) => {
            e.preventDefault();
            enable.mutate();
          }}
        >
          <p className="text-sm text-slate-600">Scan this code with your authenticator app, then enter the 6-digit code it shows.</p>
          <img
            src={"data:image/svg+xml;utf8," + encodeURIComponent(setup.qr_svg)}
            alt="QR code for your authenticator app"
            className="size-44 rounded-lg border border-slate-200 bg-white p-2"
          />
          <p className="text-xs text-slate-500">
            Can't scan? Enter this key: <code className="select-all break-all rounded bg-slate-100 px-1.5 py-0.5 font-mono">{setup.secret}</code>
          </p>
          <Field label="Code from the app">
            <TextInput inputMode="numeric" autoComplete="one-time-code" maxLength={8} value={code} onChange={(e) => setCode(e.target.value)} />
          </Field>
          <ErrorText error={enable.error} />
          <div className="flex gap-2">
            <Button type="submit" variant="primary" busy={enable.isPending} disabled={code.trim().length < 6}>
              Confirm and turn on
            </Button>
            <Button onClick={() => setSetup(null)}>Cancel</Button>
          </div>
        </form>
      )}
    </Card>
  );
}

function ChangePassword() {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [repeat, setRepeat] = useState("");
  const change = useAction(
    () => api("/auth/change-password", { method: "POST", body: { current_password: current, new_password: next } }),
    () => {
      setCurrent("");
      setNext("");
      setRepeat("");
    },
  );
  const mismatch = repeat.length > 0 && repeat !== next;
  return (
    <Card title="Change password">
      <form
        className="space-y-3"
        onSubmit={(e) => {
          e.preventDefault();
          change.mutate();
        }}
      >
        <Field label="Current password">
          <TextInput type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} required />
        </Field>
        <Field label="New password" hint="At least 12 characters.">
          <TextInput type="password" autoComplete="new-password" minLength={12} value={next} onChange={(e) => setNext(e.target.value)} required />
        </Field>
        <Field label="Repeat new password" hint={mismatch ? "The two entries differ." : undefined}>
          <TextInput type="password" autoComplete="new-password" value={repeat} onChange={(e) => setRepeat(e.target.value)} required />
        </Field>
        {change.isSuccess && <Alert tone="success">Password changed. Your other sessions were signed out.</Alert>}
        <ErrorText error={change.error} />
        <Button type="submit" variant="primary" busy={change.isPending} disabled={!current || next.length < 12 || next !== repeat}>
          Change password
        </Button>
      </form>
    </Card>
  );
}

function DeleteAccount({ isSuperadmin }: { isSuperadmin: boolean }) {
  const client = useQueryClient();
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const remove = useAction(
    () => api("/auth/delete-account", { method: "POST", body: { password, confirm } }),
    () => client.setQueryData(["auth"], { authenticated: false, user: null }),
  );
  return (
    <Card title="Delete account" className="border-red-200 lg:col-span-2">
      {isSuperadmin ? (
        <p className="text-sm text-slate-600">The superadmin account cannot be deleted from the app.</p>
      ) : (
        <form
          className="space-y-3"
          onSubmit={(e) => {
            e.preventDefault();
            remove.mutate();
          }}
        >
          <Alert tone="warning">
            This permanently deletes your account and everything in it: resumes, jobs, tailored resumes, applications, emails, settings and
            files. It cannot be undone.
          </Alert>
          <div className="grid gap-3 md:grid-cols-2">
            <Field label="Password" hint="Signed up with Google? Use “Forgot password” on the sign-in page to set one first.">
              <TextInput type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
            </Field>
            <Field label="Type DELETE MY ACCOUNT to confirm">
              <TextInput value={confirm} onChange={(e) => setConfirm(e.target.value)} />
            </Field>
          </div>
          <ErrorText error={remove.error} />
          <Button type="submit" variant="danger" busy={remove.isPending} disabled={!password || confirm !== "DELETE MY ACCOUNT"}>
            Delete my account
          </Button>
        </form>
      )}
    </Card>
  );
}

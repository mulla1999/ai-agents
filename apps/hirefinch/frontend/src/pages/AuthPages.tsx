// Public pages: sign in, register, verify email, forgot/reset password, privacy.

import { Lock, MailCheck, ShieldCheck, UserPlus } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router";
import { api } from "../api/client";
import type { AuthMessage, LoginResponse } from "../api/types";
import { AuthButtonLink, AuthInput, AuthLink, AuthShell, DevLink, FormError, FormSuccess, GoogleButton, SubmitButton } from "../components/AuthShell";
import { BRAND } from "../brand";

function Pill({ icon: Icon, children }: { icon: typeof Lock; children: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full bg-indigo-50 px-3 py-1 text-xs font-medium text-indigo-700 ring-1 ring-indigo-100">
      <Icon className="size-3.5" aria-hidden /> {children}
    </span>
  );
}

/** Runs an async form action with busy/error state. */
function useSubmit<T>(fn: () => Promise<T>, onOk?: (r: T) => void) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function submit(e?: React.FormEvent) {
    e?.preventDefault();
    setBusy(true);
    setError(null);
    try {
      onOk?.(await fn());
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return { busy, error, submit };
}

const LOGIN_ERRORS: Record<string, string> = {
  google_cancelled: "Google sign-in was cancelled.",
  google_expired: "The Google sign-in took too long. Try again.",
  google_state: "The Google sign-in could not be matched to this browser. Try again.",
  google_failed: "Google could not confirm your account. Try again.",
  google_unavailable: "Sign in with Google is not set up here.",
  registration_closed: "New sign-ups are closed.",
  domain_not_allowed: "Sign-ups are limited to specific email domains.",
  disabled: "This account is disabled. Contact the administrator.",
  conflict: "This email is linked to a different Google account.",
};

/** A pending two-factor challenge from the URL fragment (after Google sign-in), consumed once. */
function takeChallengeFromHash(): string | null {
  const match = /(?:^#|&)challenge=([^&]+)/.exec(window.location.hash);
  if (!match) return null;
  window.history.replaceState(null, "", window.location.pathname + window.location.search);
  return decodeURIComponent(match[1]);
}

export function LoginPage({ onSignedIn, expired }: { onSignedIn: () => void; expired?: boolean }) {
  const [params] = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [unverified, setUnverified] = useState(false);
  const [resent, setResent] = useState<AuthMessage | null>(null);
  const [challenge, setChallenge] = useState<string | null>(() => takeChallengeFromHash());
  const [code, setCode] = useState("");
  const errorCode = params.get("error");
  const form = useSubmit(
    async () => {
      setUnverified(false);
      try {
        return await api<LoginResponse>("/auth/login", { method: "POST", body: { email, password } });
      } catch (err) {
        if ((err as { code?: string }).code === "unverified") setUnverified(true);
        throw err;
      }
    },
    (r) => {
      if (r.two_factor_required && r.challenge) {
        setChallenge(r.challenge);
        setPassword("");
      } else {
        onSignedIn();
      }
    },
  );
  const second = useSubmit(
    () => api<LoginResponse>("/auth/login/2fa", { method: "POST", body: { challenge, code: code.trim() } }),
    () => onSignedIn(),
  );
  const resend = useSubmit(() => api<AuthMessage>("/auth/resend-verification", { method: "POST", body: { email } }), setResent);

  if (challenge) {
    return (
      <AuthShell badge={<Pill icon={ShieldCheck}>Two-factor sign-in</Pill>} title="Enter your code" subtitle="Open your authenticator app and enter the 6-digit code for HireFinch.">
        <form className="space-y-5" onSubmit={second.submit}>
          <AuthInput
            label="Authentication code"
            name="one-time-code"
            autoComplete="one-time-code"
            inputMode="text"
            autoFocus
            required
            value={code}
            onChange={(e) => setCode(e.target.value)}
            placeholder="123456"
            invalid={!!second.error}
            hint="Lost your phone? Enter one of your recovery codes instead (like abc123-def456)."
          />
          <FormError message={second.error} />
          <SubmitButton busy={second.busy} disabled={code.trim().length < 6}>
            Verify and sign in
          </SubmitButton>
        </form>
        <p className="mt-8 text-center text-sm text-slate-600">
          <button type="button" className="font-medium text-indigo-700 hover:underline" onClick={() => { setChallenge(null); setCode(""); }}>
            Start over
          </button>
        </p>
      </AuthShell>
    );
  }

  return (
    <AuthShell badge={<Pill icon={Lock}>Private workspace</Pill>} title="Welcome back" subtitle="Sign in to review your matches, resumes and applications.">
      {expired && <p className="mb-5 rounded-xl bg-amber-50 px-3.5 py-2.5 text-sm text-amber-800 ring-1 ring-amber-100">Your session ended. Sign in again to continue.</p>}
      {errorCode && <div className="mb-5"><FormError message={LOGIN_ERRORS[errorCode] ?? "Sign-in did not complete. Try again."} /></div>}
      <form className="space-y-5" onSubmit={form.submit}>
        <AuthInput label="Email" name="email" type="email" autoComplete="email" autoFocus required value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@example.com" />
        <div>
          <AuthInput label="Password" name="password" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} placeholder="Enter your password" invalid={!!form.error} />
          <div className="mt-2 text-right text-sm">
            <AuthLink to="/forgot-password">Forgot password?</AuthLink>
          </div>
        </div>
        <FormError message={form.error} />
        {unverified && !resent && (
          <button type="button" className="text-sm font-medium text-indigo-700 hover:underline" onClick={() => resend.submit()} disabled={resend.busy}>
            Send the confirmation link again
          </button>
        )}
        {resent && (
          <>
            <FormSuccess>{resent.message}</FormSuccess>
            <DevLink link={resent.dev_link} />
          </>
        )}
        <SubmitButton busy={form.busy} disabled={!email || !password}>
          Sign in
        </SubmitButton>
      </form>
      <GoogleButton />
      <p className="mt-8 text-center text-sm text-slate-600">
        New here? <AuthLink to="/register">Create an account</AuthLink>
      </p>
    </AuthShell>
  );
}

export function RegisterPage() {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [consent, setConsent] = useState(false);
  const [done, setDone] = useState<AuthMessage | null>(null);
  const form = useSubmit(
    () => api<AuthMessage>("/auth/register", { method: "POST", body: { email, password, full_name: name || null, consent } }),
    setDone,
  );
  const short = password.length > 0 && password.length < 12;
  if (done?.active) {
    return (
      <AuthShell badge={<Pill icon={UserPlus}>Welcome</Pill>} title="Your account is ready" subtitle={`Sign in with ${email} and the password you just chose.`}>
        <AuthButtonLink to="/login">Sign in</AuthButtonLink>
      </AuthShell>
    );
  }
  if (done) {
    return (
      <AuthShell badge={<Pill icon={MailCheck}>Almost there</Pill>} title="Check your email" subtitle={`We sent a confirmation link to ${email}.`}>
        <FormSuccess>{done.message} The link works for 48 hours.</FormSuccess>
        <DevLink link={done.dev_link} />
        <p className="mt-8 text-center text-sm text-slate-600">
          Confirmed already? <AuthLink to="/login">Sign in</AuthLink>
        </p>
      </AuthShell>
    );
  }
  return (
    <AuthShell badge={<Pill icon={UserPlus}>Free account</Pill>} title="Create your account" subtitle="Bring your resume; the agent finds roles and tailors it for each one.">
      <form className="space-y-5" onSubmit={form.submit}>
        <AuthInput label="Full name" name="name" autoComplete="name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Your name" />
        <AuthInput label="Email" name="email" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@example.com" />
        <AuthInput
          label="Password"
          name="new-password"
          type="password"
          autoComplete="new-password"
          required
          minLength={12}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          invalid={short}
          hint={short ? `${12 - password.length} more characters needed` : "At least 12 characters. A short phrase is easiest to remember."}
        />
        <label className="flex items-start gap-2.5 text-sm text-slate-600">
          <input type="checkbox" className="mt-0.5 size-4 rounded border-slate-300 accent-indigo-600" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
          <span>
            I agree that my account, resume and settings are stored to provide the service, as described in the{" "}
            <AuthLink to="/privacy">privacy notice</AuthLink>.
          </span>
        </label>
        <FormError message={form.error} />
        <SubmitButton busy={form.busy} disabled={!email || password.length < 12 || !consent}>
          Create account
        </SubmitButton>
      </form>
      <GoogleButton label="Sign up with Google" />
      <p className="mt-3 text-center text-xs text-slate-500">
        Signing up with Google means you accept the <AuthLink to="/privacy">privacy notice</AuthLink>.
      </p>
      <p className="mt-8 text-center text-sm text-slate-600">
        Have an account? <AuthLink to="/login">Sign in</AuthLink>
      </p>
    </AuthShell>
  );
}

export function VerifyEmailPage() {
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const [state, setState] = useState<"working" | "done" | "error">("working");
  const [message, setMessage] = useState("");
  const started = useRef(false);
  useEffect(() => {
    if (started.current) return; // StrictMode runs effects twice; the token is single-use
    started.current = true;
    if (!token) {
      setState("error");
      setMessage("This link is missing its token.");
      return;
    }
    api<{ verified: boolean; email: string }>("/auth/verify-email", { method: "POST", body: { token } })
      .then((r) => {
        setState("done");
        setMessage(r.email);
      })
      .catch((err) => {
        setState("error");
        setMessage((err as Error).message);
      });
  }, [token]);
  return (
    <AuthShell badge={<Pill icon={MailCheck}>Email confirmation</Pill>} title={state === "done" ? "Email confirmed" : state === "error" ? "Link not valid" : "Confirming…"}>
      {state === "working" && <p className="text-sm text-slate-500">One moment…</p>}
      {state === "done" && (
        <>
          <FormSuccess>Your account {message} is active.</FormSuccess>
          <div className="mt-6">
            <AuthButtonLink to="/login">Sign in</AuthButtonLink>
          </div>
        </>
      )}
      {state === "error" && (
        <>
          <FormError message={message} />
          <p className="mt-6 text-sm text-slate-600">
            Sign in to get a new confirmation link: <AuthLink to="/login">Sign in</AuthLink>
          </p>
        </>
      )}
    </AuthShell>
  );
}

export function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [done, setDone] = useState<AuthMessage | null>(null);
  const form = useSubmit(() => api<AuthMessage>("/auth/forgot-password", { method: "POST", body: { email } }), setDone);
  return (
    <AuthShell badge={<Pill icon={Lock}>Account recovery</Pill>} title="Reset your password" subtitle="We will email you a link to choose a new one.">
      {done ? (
        <>
          <FormSuccess>{done.message} The link works for 1 hour.</FormSuccess>
          <DevLink link={done.dev_link} />
        </>
      ) : (
        <form className="space-y-5" onSubmit={form.submit}>
          <AuthInput label="Email" name="email" type="email" autoComplete="email" autoFocus required value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@example.com" />
          <FormError message={form.error} />
          <SubmitButton busy={form.busy} disabled={!email}>
            Send reset link
          </SubmitButton>
        </form>
      )}
      <p className="mt-8 text-center text-sm text-slate-600">
        Remembered it? <AuthLink to="/login">Sign in</AuthLink>
      </p>
    </AuthShell>
  );
}

export function ResetPasswordPage() {
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const [password, setPassword] = useState("");
  const [repeat, setRepeat] = useState("");
  const [done, setDone] = useState(false);
  const form = useSubmit(() => api("/auth/reset-password", { method: "POST", body: { token, password } }), () => setDone(true));
  const mismatch = repeat.length > 0 && repeat !== password;
  return (
    <AuthShell badge={<Pill icon={Lock}>Account recovery</Pill>} title={done ? "Password changed" : "Choose a new password"}>
      {done ? (
        <>
          <FormSuccess>Your password is changed and every other session was signed out.</FormSuccess>
          <div className="mt-6">
            <AuthButtonLink to="/login">Sign in</AuthButtonLink>
          </div>
        </>
      ) : !token ? (
        <FormError message="This link is missing its token. Request a new one." />
      ) : (
        <form className="space-y-5" onSubmit={form.submit}>
          <AuthInput label="New password" name="new-password" type="password" autoComplete="new-password" required minLength={12} value={password} onChange={(e) => setPassword(e.target.value)} hint="At least 12 characters." />
          <AuthInput label="Repeat it" name="repeat-password" type="password" autoComplete="new-password" required value={repeat} onChange={(e) => setRepeat(e.target.value)} invalid={mismatch} hint={mismatch ? "The two entries differ." : undefined} />
          <FormError message={form.error} />
          <SubmitButton busy={form.busy} disabled={password.length < 12 || password !== repeat}>
            Change password
          </SubmitButton>
        </form>
      )}
      <p className="mt-8 text-center text-sm text-slate-600">
        <AuthLink to="/forgot-password">Request a new link</AuthLink>
      </p>
    </AuthShell>
  );
}

export function PrivacyPage() {
  return (
    <AuthShell title="Privacy notice" subtitle={`What ${BRAND} stores about you, and how to remove it.`}>
      <div className="space-y-4 text-sm leading-relaxed text-slate-700">
        <section>
          <h3 className="font-semibold text-slate-900">What is stored</h3>
          <ul className="mt-1 list-disc space-y-1 pl-5">
            <li>Your account: email, name and a salted hash of your password (never the password itself).</li>
            <li>The resumes you upload, the jobs found for you, the tailored resumes generated from them, and your application and email history.</li>
            <li>Your settings, including email and AI provider connections. Passwords and API keys are encrypted and are never shown again, not even to administrators.</li>
            <li>An activity log of actions taken in your account.</li>
          </ul>
        </section>
        <section>
          <h3 className="font-semibold text-slate-900">Who can see it</h3>
          <p className="mt-1">Only you. Administrators see account details and counts (for example, how many jobs you have), not your resume, jobs or messages.</p>
        </section>
        <section>
          <h3 className="font-semibold text-slate-900">Where your data goes</h3>
          <p className="mt-1">Emails are sent through the email account you connect. If you connect an AI provider and turn it on, resume and job text are sent to that provider to reword summaries and emails.</p>
        </section>
        <section>
          <h3 className="font-semibold text-slate-900">Deleting your data</h3>
          <p className="mt-1">Account → Delete account removes your account and everything in it, including uploaded and generated files. It cannot be undone.</p>
        </section>
      </div>
      <p className="mt-8 text-center text-sm text-slate-600">
        <AuthLink to="/register">Create an account</AuthLink> · <AuthLink to="/login">Sign in</AuthLink>
      </p>
    </AuthShell>
  );
}

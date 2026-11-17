// Administration: overview, users, platform settings (superadmin), platform audit.
// Admins see account details and counts only, never users' resumes, jobs, messages or secrets.

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api, qs } from "../api/client";
import type {
  AdminAuditEvent,
  AdminOverview,
  AdminSettings,
  AdminUser,
  AdminUsers,
  IntegrationView,
  PlatformLimits,
  RegistrationSettings,
  RetentionSettings,
  TestResult,
} from "../api/types";
import { useMe } from "../auth";
import { EmailForm, SecretInput } from "../components/ConnectionForms";
import { TasksTable } from "../components/TasksTable";
import {
  Alert,
  Badge,
  Button,
  Card,
  Checkbox,
  Empty,
  ErrorText,
  Field,
  ListInput,
  Loading,
  NumberInput,
  PageHeader,
  Pager,
  Select,
  TextInput,
  formatDate,
  useAction,
} from "../components/ui";

const ROLE_TONE = { superadmin: "indigo", admin: "blue", user: "slate" } as const;
const STATUS_TONE = { active: "green", pending_verification: "amber", disabled: "red" } as const;

function Stat({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <div className="text-2xl font-semibold text-slate-900">{value}</div>
      <div className="mt-1 text-xs text-slate-500">{label}</div>
    </div>
  );
}

export function AdminOverviewPage() {
  const me = useMe();
  const query = useQuery({ queryKey: ["admin", "overview"], queryFn: () => api<AdminOverview>("/admin/overview") });
  if (query.isLoading) return <Loading />;
  if (query.error) return <ErrorText error={query.error} />;
  const o = query.data!;
  return (
    <>
      <PageHeader title="Administration" subtitle="Platform health at a glance." />
      {!o.system_email_configured && (
        <div className="mb-4">
          <Alert tone="warning">
            No platform email is set up, so verification and password-reset emails cannot be sent. {me.role === "superadmin" ? "Add it in Platform settings." : "Ask the superadmin to add it."}
          </Alert>
        </div>
      )}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <Stat label="Accounts" value={o.users.total} />
        <Stat label="Active" value={o.users.active ?? 0} />
        <Stat label="Awaiting email confirmation" value={o.users.pending_verification ?? 0} />
        <Stat label="Disabled" value={o.users.disabled ?? 0} />
        <Stat label="Signed-in sessions" value={o.active_sessions} />
        <Stat label="Applications submitted" value={o.applications} />
      </div>
      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Card title="Registration">
          <p className="text-sm">
            Sign-ups are <Badge tone={o.registration.open ? "green" : "red"}>{o.registration.open ? "open" : "closed"}</Badge>
            {o.registration.allowed_domains.length > 0 && <span className="text-slate-600"> · limited to {o.registration.allowed_domains.join(", ")}</span>}
          </p>
          <p className="mt-2 text-sm text-slate-600">
            {o.registration.verify_email === false ? "New accounts work straight away (no email confirmation)." : "New accounts confirm their email first."}
          </p>
          <p className="mt-2 text-sm text-slate-600">Jobs tracked across all accounts: {o.jobs}</p>
        </Card>
        <Card title="Limits per account">
          <LimitsList limits={o.limits} />
        </Card>
      </div>
      <div className="mt-4">
        <TasksTable tasks={o.tasks} editable={me.role === "superadmin"} />
      </div>
    </>
  );
}

const LIMIT_LABELS: Record<keyof PlatformLimits, string> = {
  max_resumes: "Master resumes per account",
  max_boards_per_source: "Companies per job source",
  max_career_pages: "Career pages watched",
  min_discovery_minutes: "Minimum minutes between discovery runs",
  daily_outreach_cap: "Recruiter emails per day",
  daily_application_cap: "Applications per day",
};

function LimitsList({ limits }: { limits: PlatformLimits }) {
  return (
    <dl className="grid grid-cols-[1fr_auto] gap-y-1.5 text-sm">
      {(Object.keys(LIMIT_LABELS) as (keyof PlatformLimits)[]).map((k) => (
        <div key={k} className="contents">
          <dt className="text-slate-600">{LIMIT_LABELS[k]}</dt>
          <dd className="text-right font-medium">{limits[k]}</dd>
        </div>
      ))}
    </dl>
  );
}

export function AdminUsersPage() {
  const me = useMe();
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [role, setRole] = useState("");
  const [page, setPage] = useState(1);
  const pageSize = 50;
  const query = useQuery({
    queryKey: ["admin", "users", q, status, role, page],
    queryFn: () => api<AdminUsers>(`/admin/users${qs({ q, status, role, page, page_size: pageSize })}`),
  });
  return (
    <>
      <PageHeader title="Users" subtitle="Accounts and their activity counts. Account content stays private to each user." />
      <Card>
        <div className="mb-3 grid gap-3 sm:grid-cols-[2fr_1fr_1fr]">
          <Field label="Search">
            <TextInput value={q} placeholder="Name or email" onChange={(e) => { setQ(e.target.value); setPage(1); }} />
          </Field>
          <Field label="Status">
            <Select value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }}>
              <option value="">Any</option>
              <option value="active">Active</option>
              <option value="pending_verification">Awaiting verification</option>
              <option value="disabled">Disabled</option>
            </Select>
          </Field>
          <Field label="Role">
            <Select value={role} onChange={(e) => { setRole(e.target.value); setPage(1); }}>
              <option value="">Any</option>
              <option value="superadmin">Owner</option>
              <option value="admin">Admin</option>
              <option value="user">User</option>
            </Select>
          </Field>
        </div>
        {query.isLoading ? (
          <Loading />
        ) : query.error ? (
          <ErrorText error={query.error} />
        ) : query.data!.items.length === 0 ? (
          <Empty>No accounts match.</Empty>
        ) : (
          <>
            <div className={`hidden pb-2 text-xs font-medium uppercase text-slate-500 ${USER_GRID}`}>
              <span>Account</span>
              <span>Role</span>
              <span>Status</span>
              <span className="text-right">Resumes</span>
              <span className="text-right">Jobs</span>
              <span className="text-right">Applied</span>
              <span>Joined</span>
              <span>Last sign-in</span>
              <span />
            </div>
            <ul className="divide-y divide-slate-100">
              {query.data!.items.map((u) => (
                <UserRow key={u.id} user={u} meId={me.id} superadmin={me.role === "superadmin"} />
              ))}
            </ul>
            <Pager page={page} total={query.data!.total} pageSize={pageSize} onPage={setPage} />
          </>
        )}
      </Card>
    </>
  );
}

const ROLE_LABEL: Record<string, string> = { superadmin: "Owner", admin: "Admin", user: "User" };
const USER_STATUS_LABEL: Record<string, string> = { active: "Active", pending_verification: "Awaiting email confirmation", disabled: "Disabled" };
// A table row on wide screens, a card on phones.
const USER_GRID = "xl:grid xl:grid-cols-[minmax(0,2fr)_5rem_7rem_4rem_4rem_4rem_6rem_8rem_minmax(0,1.6fr)] xl:items-start xl:gap-3";

function UserRow({ user, meId, superadmin }: { user: AdminUser; meId: number; superadmin: boolean }) {
  const setStatus = useAction((status: string) => api(`/admin/users/${user.id}/status`, { method: "POST", body: { status } }));
  const setRole = useAction((role: string) => api(`/admin/users/${user.id}/role`, { method: "POST", body: { role } }));
  const remove = useAction(() => api(`/admin/users/${user.id}`, { method: "DELETE" }));
  // Nobody acts on themselves or on the superadmin; only the superadmin acts on admins.
  const protectedRow = user.id === meId || user.role === "superadmin" || (user.role === "admin" && !superadmin);
  return (
    <li className={`py-3 text-sm ${USER_GRID}`}>
      <div className="min-w-0">
        <div className="font-medium">{user.full_name || "—"}</div>
        <div className="break-all text-xs text-slate-500">{user.email}</div>
      </div>
      {/* Phones: badges and counts on two short lines under the name. */}
      <div className="mt-1.5 flex flex-wrap items-center gap-1.5 xl:contents">
        <span className="xl:pt-0.5">
          <Badge tone={ROLE_TONE[user.role]}>{ROLE_LABEL[user.role] ?? user.role}</Badge>
        </span>
        <span className="xl:pt-0.5">
          <Badge tone={STATUS_TONE[user.status]}>{USER_STATUS_LABEL[user.status] ?? user.status.replaceAll("_", " ")}</Badge>
        </span>
      </div>
      <p className="mt-1 text-xs text-slate-600 xl:hidden">
        {user.resumes} resumes · {user.jobs} jobs · {user.applications} applied · joined {formatDate(user.created_at)} · last sign-in {formatDate(user.last_login_at, true)}
      </p>
      <span className="hidden text-right xl:block">{user.resumes}</span>
      <span className="hidden text-right xl:block">{user.jobs}</span>
      <span className="hidden text-right xl:block">{user.applications}</span>
      <span className="hidden text-slate-600 xl:block">{formatDate(user.created_at)}</span>
      <span className="hidden text-slate-600 xl:block">{formatDate(user.last_login_at, true)}</span>
      <div className="mt-2 xl:mt-0">
        {protectedRow ? (
          <span className="text-xs text-slate-400">{user.id === meId ? "you" : "—"}</span>
        ) : (
          <div className="flex flex-wrap gap-1.5 xl:justify-end">
            {user.status === "active" ? (
              <Button busy={setStatus.isPending} onClick={() => setStatus.mutate("disabled")}>
                Disable
              </Button>
            ) : (
              <Button busy={setStatus.isPending} onClick={() => setStatus.mutate("active")} title={user.status === "pending_verification" ? "Activates without email confirmation" : undefined}>
                Enable
              </Button>
            )}
            {superadmin && (
              <Button busy={setRole.isPending} onClick={() => setRole.mutate(user.role === "admin" ? "user" : "admin")}>
                {user.role === "admin" ? "Make user" : "Make admin"}
              </Button>
            )}
            {superadmin && (
              <Button
                variant="danger"
                busy={remove.isPending}
                onClick={() => window.confirm(`Delete ${user.email} and all of their data? This cannot be undone.`) && remove.mutate()}
              >
                Delete
              </Button>
            )}
          </div>
        )}
        <ErrorText error={setStatus.error || setRole.error || remove.error} />
      </div>
    </li>
  );
}

export function AdminSettingsPage() {
  const query = useQuery({ queryKey: ["admin", "settings"], queryFn: () => api<AdminSettings>("/admin/settings") });
  if (query.isLoading) return <Loading />;
  if (query.error) return <ErrorText error={query.error} />;
  const s = query.data!;
  return (
    <>
      <PageHeader title="Platform settings" subtitle="Superadmin only. Changes apply to every account and are recorded in the platform audit." />
      <div className="space-y-4">
        <SystemEmail key={JSON.stringify(s.system_email.config) + s.system_email.secrets_set.join()} view={s.system_email} />
        <div className="grid gap-4 lg:grid-cols-2">
          <Registration key={JSON.stringify(s.registration)} value={s.registration} />
          <Limits key={JSON.stringify(s.limits)} value={s.limits} />
          {s.google_oauth && <GoogleSignIn key={JSON.stringify(s.google_oauth.config) + s.google_oauth.secrets_set.join()} view={s.google_oauth} />}
          {s.retention && <Retention key={JSON.stringify(s.retention)} value={s.retention} />}
        </div>
      </div>
    </>
  );
}

function SystemEmail({ view }: { view: IntegrationView }) {
  const [to, setTo] = useState("");
  const [saved, setSaved] = useState(false);
  const save = useAction(
    ({ config, secrets }: { config: Record<string, unknown>; secrets: Record<string, string> }) =>
      api("/admin/settings/system_email", { method: "PUT", body: { config, secrets } }),
    () => setSaved(true),
  );
  const test = useAction(() => api<TestResult>("/admin/settings/system_email/test", { method: "POST", body: { to } }));
  return (
    <EmailForm
      title="Platform email"
      description="Sends account emails for everyone: email verification and password resets. Users' own notifications use their own email settings."
      view={view}
      actions={{
        save: (config, secrets) => {
          setSaved(false);
          save.mutate({ config, secrets });
        },
        saving: save.isPending,
        saveError: save.error,
        saved,
        testResult: test.data ?? null,
        extraActions: (
          <span className="flex items-center gap-2">
            <span className="w-56">
              <TextInput type="email" aria-label="Test recipient" placeholder="send a test to…" value={to} onChange={(e) => setTo(e.target.value)} />
            </span>
            <Button busy={test.isPending} disabled={!to || !view.configured} onClick={() => test.mutate()}>
              Send test
            </Button>
          </span>
        ),
      }}
    />
  );
}

function GoogleSignIn({ view }: { view: IntegrationView & { redirect_uri: string } }) {
  const [clientId, setClientId] = useState(String(view.config.client_id ?? ""));
  const [secret, setSecret] = useState("");
  const save = useAction(() =>
    api("/admin/settings/google_oauth", { method: "PUT", body: { config: { client_id: clientId }, secrets: { client_secret: secret } } }),
    () => setSecret(""),
  );
  const ready = Boolean(view.config.client_id) && view.secrets_set.includes("client_secret");
  return (
    <Card title={<span className="flex items-center gap-2">Sign in with Google {ready ? <Badge tone="green">on</Badge> : <Badge tone="amber">off</Badge>}</span>}>
      <div className="space-y-3">
        <p className="text-sm text-slate-600">
          Create an OAuth client (type <em>Web application</em>) in Google Cloud Console → APIs &amp; Services → Credentials, add the
          redirect URI below, then paste the client id and secret here. The button appears on the sign-in page once both are saved.
        </p>
        <Field label="Authorized redirect URI (copy into Google)">
          <TextInput value={view.redirect_uri} readOnly onFocus={(e) => e.currentTarget.select()} />
        </Field>
        <Field label="Client ID" hint="Ends with .apps.googleusercontent.com">
          <TextInput value={clientId} onChange={(e) => setClientId(e.target.value)} />
        </Field>
        <SecretInput label="Client secret" name="client_secret" view={view} value={secret} onChange={setSecret} />
        <Button variant="primary" busy={save.isPending} onClick={() => save.mutate()}>
          Save
        </Button>
        {save.isSuccess && <Alert tone="success">Saved.</Alert>}
        <ErrorText error={save.error} />
      </div>
    </Card>
  );
}

function Retention({ value }: { value: RetentionSettings }) {
  const [r, setR] = useState<RetentionSettings>(value);
  const save = useAction(() => api("/admin/settings/retention", { method: "PUT", body: { config: r } }));
  const set = (k: keyof RetentionSettings) => (v: number | null) => setR({ ...r, [k]: v ?? 0 });
  const invalid = r.inactive_days !== 0 && r.inactive_days < 90;
  return (
    <Card title="Data retention">
      <div className="space-y-3">
        <p className="text-sm text-slate-600">
          Accounts with no sign-in for the set number of days get a warning email; if nobody signs in within the grace period, the
          account and all its data are deleted. Signing in cancels it. The superadmin account is never deleted. Say how long you keep
          data in your privacy notice.
        </p>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Delete accounts inactive for (days)" hint={invalid ? "At least 90, or 0 to keep accounts forever" : "0 = keep forever"}>
            <NumberInput value={r.inactive_days} min={0} onChange={set("inactive_days")} />
          </Field>
          <Field label="Warning before deletion (days)" hint="At least 7">
            <NumberInput value={r.warn_days} min={7} onChange={set("warn_days")} />
          </Field>
          <Field label="Keep activity log (days)" hint="At least 30">
            <NumberInput value={r.audit_days} min={30} onChange={set("audit_days")} />
          </Field>
          <Field label="Keep sent notifications (days)" hint="At least 30">
            <NumberInput value={r.notification_days} min={30} onChange={set("notification_days")} />
          </Field>
        </div>
        <Button variant="primary" busy={save.isPending} disabled={invalid} onClick={() => save.mutate()}>
          Save
        </Button>
        {save.isSuccess && <Alert tone="success">Saved.</Alert>}
        <ErrorText error={save.error} />
      </div>
    </Card>
  );
}

function Registration({ value }: { value: RegistrationSettings }) {
  const [open, setOpen] = useState(value.open);
  const [verify, setVerify] = useState(value.verify_email);
  const [domains, setDomains] = useState(value.allowed_domains);
  const save = useAction(() => api("/admin/settings/registration", { method: "PUT", body: { config: { open, allowed_domains: domains, verify_email: verify } } }));
  return (
    <Card title="Registration">
      <div className="space-y-3">
        <Checkbox label="Anyone can create an account" checked={open} onChange={setOpen} />
        <Checkbox label="Require email confirmation (needs the Platform email)" checked={verify} onChange={setVerify} />
        {!verify && (
          <Alert tone="warning">
            New accounts work straight away. Anyone could sign up with an address that isn't theirs, and “Forgot password” still needs the Platform email. Fine for friends; turn it
            back on before sharing the link widely.
          </Alert>
        )}
        <Field label="Allowed email domains" hint="Empty = any domain. Example: example.com, example.org">
          <ListInput value={domains} onChange={setDomains} rows={2} />
        </Field>
        <Button variant="primary" busy={save.isPending} onClick={() => save.mutate()}>
          Save
        </Button>
        {save.isSuccess && <Alert tone="success">Saved.</Alert>}
        <ErrorText error={save.error} />
      </div>
    </Card>
  );
}

function Limits({ value }: { value: PlatformLimits }) {
  const [limits, setLimits] = useState<PlatformLimits>(value);
  const save = useAction(() => api("/admin/settings/limits", { method: "PUT", body: { config: limits } }));
  return (
    <Card title="Limits per account">
      <div className="grid gap-3 sm:grid-cols-2">
        {(Object.keys(LIMIT_LABELS) as (keyof PlatformLimits)[]).map((k) => (
          <Field key={k} label={LIMIT_LABELS[k]}>
            <NumberInput min={1} value={limits[k]} onChange={(v) => setLimits({ ...limits, [k]: v ?? 1 })} />
          </Field>
        ))}
      </div>
      <div className="mt-3 space-y-2">
        <Button variant="primary" busy={save.isPending} onClick={() => save.mutate()}>
          Save
        </Button>
        {save.isSuccess && <Alert tone="success">Saved.</Alert>}
        <ErrorText error={save.error} />
      </div>
    </Card>
  );
}

export function AdminAuditPage() {
  const [q, setQ] = useState("");
  const [level, setLevel] = useState("");
  const [page, setPage] = useState(1);
  const pageSize = 100;
  const query = useQuery({
    queryKey: ["admin", "audit", q, level, page],
    queryFn: () => api<{ total: number; items: AdminAuditEvent[] }>(`/admin/audit${qs({ q, level, page, page_size: pageSize })}`),
  });
  return (
    <>
      <PageHeader title="Platform audit" subtitle="Account, administration, platform and scheduler events. Activity inside accounts stays private." />
      <Card>
        <div className="mb-3 grid gap-3 md:grid-cols-[1fr_10rem]">
          <Field label="Search">
            <TextInput value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} />
          </Field>
          <Field label="Level">
            <Select value={level} onChange={(e) => { setLevel(e.target.value); setPage(1); }}>
              <option value="">Any</option>
              <option value="info">Info</option>
              <option value="warning">Warning</option>
              <option value="error">Error</option>
            </Select>
          </Field>
        </div>
        {query.isLoading ? (
          <Loading />
        ) : query.error ? (
          <ErrorText error={query.error} />
        ) : query.data!.items.length === 0 ? (
          <Empty>No events.</Empty>
        ) : (
          <>
            <ul className="divide-y divide-slate-100 text-sm">
              {query.data!.items.map((e) => (
                <li key={e.id} className="min-w-0 py-2.5">
                  <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
                    <span>{formatDate(e.at, true)}</span>
                    <Badge tone={e.level === "error" ? "red" : e.level === "warning" ? "amber" : "slate"}>{e.action.replaceAll(/[._]/g, " ")}</Badge>
                    {e.user_email && <span className="min-w-0 break-all">{e.user_email}</span>}
                  </div>
                  <p className="mt-1 break-words text-slate-800">{e.message}</p>
                </li>
              ))}
            </ul>
            <Pager page={page} total={query.data!.total} pageSize={pageSize} onPage={setPage} />
          </>
        )}
      </Card>
    </>
  );
}

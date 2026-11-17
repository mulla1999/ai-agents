// Forms for connections (email, AI provider, Adzuna). Secret fields are write-only: the API never
// returns them, so they start empty and a blank value keeps what is stored.

import { ExternalLink } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { api } from "../api/client";
import type { IntegrationView, TestResult } from "../api/types";
import { Alert, Badge, Button, Card, Checkbox, ErrorText, Field, NumberInput, Select, TextInput, formatDate } from "./ui";

type Config = Record<string, unknown>;
type Secrets = Record<string, string>;

export interface ConnectionActions {
  save: (config: Config, secrets: Secrets) => void;
  saving: boolean;
  saveError: unknown;
  saved?: boolean;
  remove?: () => void;
  removing?: boolean;
  test?: () => void;
  testing?: boolean;
  testResult?: TestResult | null;
  testLabel?: string;
  extraActions?: ReactNode;
}

function str(value: unknown): string {
  return value === null || value === undefined ? "" : String(value);
}

export function SecretInput({ label, name, view, value, onChange, hint }: { label: string; name: string; view: IntegrationView; value: string; onChange: (v: string) => void; hint?: ReactNode }) {
  const isSet = view.secrets_set.includes(name);
  return (
    <Field label={label} hint={hint}>
      <TextInput
        type="password"
        autoComplete="new-password"
        value={value}
        placeholder={isSet ? "•••••• saved — leave blank to keep" : ""}
        onChange={(e) => onChange(e.target.value)}
      />
    </Field>
  );
}

function StatusBadges({ view }: { view: IntegrationView }) {
  return (
    <span className="flex flex-wrap gap-1.5">
      {view.configured ? <Badge tone="green">configured</Badge> : <Badge tone="amber">not set up</Badge>}
      {view.verified_at && <Badge tone="indigo" title={`tested ${formatDate(view.verified_at, true)}`}>tested</Badge>}
      {view.error && <Badge tone="red">cannot decrypt</Badge>}
    </span>
  );
}

function Actions({ a, onSave, view }: { a: ConnectionActions; onSave: () => void; view: IntegrationView }) {
  return (
    <div className="mt-4 space-y-2">
      <div className="flex flex-wrap gap-2">
        <Button variant="primary" busy={a.saving} onClick={onSave}>
          Save
        </Button>
        {a.test && (
          <Button busy={a.testing} disabled={!view.configured} onClick={a.test}>
            {a.testLabel ?? "Test"}
          </Button>
        )}
        {a.extraActions}
        {a.remove && view.configured && (
          <Button variant="ghost" busy={a.removing} className="ml-auto text-red-700" onClick={() => window.confirm("Remove these settings?") && a.remove?.()}>
            Remove
          </Button>
        )}
      </div>
      {a.saved && !a.saveError && <Alert tone="success">Saved.</Alert>}
      <ErrorText error={a.saveError} />
      {a.testResult && <Alert tone={a.testResult.ok ? "success" : "error"}>{a.testResult.message}</Alert>}
      {view.error && <Alert tone="error">{view.error}. Enter the secrets again.</Alert>}
    </div>
  );
}


type GuideLink = { label: string; href: string };

/** Step-by-step help for one connection: open until it is set up, then collapsed. */
function SetupGuide({ open, title = "How to set this up", steps, links = [], actions, note }: {
  open: boolean;
  title?: string;
  steps: ReactNode[];
  links?: GuideLink[];
  actions?: ReactNode;
  note?: ReactNode;
}) {
  return (
    <details open={open} className="group mb-4 rounded-xl border border-emerald-200 bg-emerald-50/60 text-sm text-slate-700 open:pb-3">
      <summary className="cursor-pointer select-none list-none px-3.5 py-2.5 font-medium text-emerald-900 marker:hidden">
        <span className="mr-1 inline-block transition group-open:rotate-90">›</span> {title}
      </summary>
      <div className="px-3.5">
        <ol className="list-decimal space-y-1 pl-5 text-xs leading-relaxed">
          {steps.map((step, i) => (
            <li key={i}>{step}</li>
          ))}
        </ol>
        {(links.length > 0 || actions) && (
          <div className="mt-2.5 flex flex-wrap gap-2">
            {links.map((l) => (
              <a key={l.href} href={l.href} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-emerald-700">
                {l.label} <ExternalLink className="size-3.5" aria-hidden />
              </a>
            ))}
            {actions}
          </div>
        )}
        {note && <p className="mt-2 text-[0.6875rem] text-slate-500">{note}</p>}
      </div>
    </details>
  );
}

function FillButton({ onClick, children }: { onClick: () => void; children: ReactNode }) {
  return (
    <button type="button" onClick={onClick} className="rounded-lg border border-emerald-300 bg-white px-3 py-1.5 text-xs font-medium text-emerald-800 hover:bg-emerald-50">
      {children}
    </button>
  );
}

const APP_PASSWORD_STEPS = [
  <>Turn on <b>2-Step Verification</b> for your Google account (required for app passwords).</>,
  <>Open <b>App passwords</b>, type a name such as “HireFinch”, click <b>Create</b>, and copy the 16-letter password.</>,
];
const GOOGLE_LINKS: GuideLink[] = [
  { label: "Turn on 2-Step Verification", href: "https://myaccount.google.com/signinoptions/twosv" },
  { label: "Create an App Password", href: "https://myaccount.google.com/apppasswords" },
];

export function EmailForm({ title, description, view, actions }: { title: string; description: ReactNode; view: IntegrationView; actions: ConnectionActions }) {
  const c = view.config;
  const [provider, setProvider] = useState(str(c.provider) || "smtp");
  const [host, setHost] = useState(str(c.host));
  const [port, setPort] = useState<number | null>((c.port as number) ?? 587);
  const [username, setUsername] = useState(str(c.username));
  const [from, setFrom] = useState(str(c.from_address));
  const [starttls, setStarttls] = useState(c.starttls === undefined ? true : Boolean(c.starttls));
  const [clientId, setClientId] = useState(str(c.client_id));
  const [secrets, setSecrets] = useState<Secrets>({});
  const setSecret = (k: string) => (v: string) => setSecrets({ ...secrets, [k]: v });
  const save = () => {
    const config =
      provider === "gmail_api"
        ? { provider, client_id: clientId, from_address: from }
        : provider === "resend"
          ? { provider, from_address: from }
          : { provider, host, port: port ?? 587, username: username || null, from_address: from, starttls };
    actions.save(config, secrets);
    setSecrets({});
  };
  return (
    <Card title={<span className="flex flex-wrap items-center gap-2">{title} <StatusBadges view={view} /></span>}>
      <p className="mb-3 text-sm text-slate-600">{description}</p>
      {view.mode && <p className="mb-3 text-xs text-slate-500">Currently: {view.mode}</p>}
      <SetupGuide
        open={!view.configured}
        title="How to set this up with Gmail (free, about 3 minutes)"
        steps={[
          ...APP_PASSWORD_STEPS,
          <>Click <b>Fill in Gmail settings</b> below, enter your Gmail address in <b>From address</b> and <b>Username</b>, and paste the app password as <b>Password</b>.</>,
          <>Click <b>Save</b>, then <b>Send test email</b>.</>,
        ]}
        links={GOOGLE_LINKS}
        actions={
          <FillButton
            onClick={() => {
              setProvider("smtp");
              setHost("smtp.gmail.com");
              setPort(587);
              setStarttls(true);
              if (from && !username) setUsername(from);
            }}
          >
            Fill in Gmail settings
          </FillButton>
        }
        note="Use an app password, never your Google account password. Outlook and other providers work too with their SMTP settings."
      />
      <div className="grid gap-3 md:grid-cols-2">
        <Field label="Provider">
          <Select value={provider} onChange={(e) => setProvider(e.target.value)}>
            <option value="smtp">SMTP (Gmail app password, Outlook, any mail server)</option>
            <option value="gmail_api">Gmail API (OAuth, send-only)</option>
            <option value="resend">Resend (transactional, high volume)</option>
          </Select>
        </Field>
        <Field label="From address">
          <TextInput type="email" value={from} onChange={(e) => setFrom(e.target.value)} placeholder="you@gmail.com" />
        </Field>
        {provider === "resend" ? (
          <SecretInput label="Resend API key" name="api_key" view={view} value={secrets.api_key ?? ""} onChange={setSecret("api_key")}
            hint="From resend.com → API keys. The from address must be on a domain you verified in Resend." />
        ) : provider === "smtp" ? (
          <>
            <Field label="SMTP host" hint="e.g. smtp.gmail.com">
              <TextInput value={host} onChange={(e) => setHost(e.target.value)} />
            </Field>
            <Field label="Port" hint="587 (STARTTLS) or 465 (SSL)">
              <NumberInput value={port} onChange={setPort} />
            </Field>
            <Field label="Username" hint="Usually your full email address">
              <TextInput value={username} autoComplete="off" onChange={(e) => setUsername(e.target.value)} />
            </Field>
            <SecretInput label="Password" name="password" view={view} value={secrets.password ?? ""} onChange={setSecret("password")}
              hint="For Gmail, an App Password (myaccount.google.com/apppasswords), never your account password." />
            <div className="md:col-span-2">
              <Checkbox label="Use STARTTLS" checked={starttls} onChange={setStarttls} />
            </div>
          </>
        ) : (
          <>
            <Field label="OAuth client ID">
              <TextInput value={clientId} onChange={(e) => setClientId(e.target.value)} />
            </Field>
            <SecretInput label="Client secret" name="client_secret" view={view} value={secrets.client_secret ?? ""} onChange={setSecret("client_secret")} />
            <SecretInput label="Refresh token" name="refresh_token" view={view} value={secrets.refresh_token ?? ""} onChange={setSecret("refresh_token")}
              hint="Granted with only the gmail.send scope." />
          </>
        )}
      </div>
      <Actions a={actions} onSave={save} view={view} />
    </Card>
  );
}

const LLM_PROVIDERS = {
  gemini: "Google Gemini (free key)",
  openai_compatible: "OpenAI or OpenAI-compatible (incl. Groq, free)",
  azure_openai: "Azure OpenAI (incl. Azure AI Foundry)",
} as const;

const GROQ_URL = "https://api.groq.com/openai/v1";
type ModelChoice = { id: string; label: string; recommended: boolean };

/** Models this key can use, recommended first; "Other" lets you type any name. */
function ModelPicker({ provider, apiKey, baseUrl, hasSavedKey, value, onChange }: {
  provider: "gemini" | "openai_compatible";
  apiKey: string;
  baseUrl: string;
  hasSavedKey: boolean;
  value: string;
  onChange: (v: string) => void;
}) {
  const [models, setModels] = useState<ModelChoice[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [other, setOther] = useState(false);
  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await api<{ models: ModelChoice[]; recommended: string | null }>("/integrations/llm/models", {
        method: "POST",
        body: { provider, api_key: apiKey || null, base_url: provider === "openai_compatible" ? baseUrl || null : null },
      });
      setModels(r.models);
      if (r.recommended && (!value || !r.models.some((m) => m.id === value))) onChange(r.recommended);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  };
  // Load once a key is available: the saved one, or one you just pasted.
  useEffect(() => {
    if (!apiKey && !hasSavedKey) return;
    const t = setTimeout(load, apiKey ? 700 : 0);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [apiKey, provider, baseUrl, hasSavedKey]);
  const listed = models?.some((m) => m.id === value);
  return (
    <Field label="Model" hint={models ? "Only models your key can use. The recommended one suits HireFinch best." : "Enter your API key to see the models it can use."}>
      <div className="flex gap-2">
        {models && !other ? (
          <Select value={listed ? value : ""} onChange={(e) => (e.target.value === "__other" ? setOther(true) : onChange(e.target.value))}>
            {!listed && <option value="">Choose a model…</option>}
            {models.map((m) => (
              <option key={m.id} value={m.id}>
                {m.label}
              </option>
            ))}
            <option value="__other">Other (type a name)…</option>
          </Select>
        ) : (
          <TextInput value={value} onChange={(e) => onChange(e.target.value)} placeholder={provider === "gemini" ? "gemini-3.5-flash" : "llama-3.3-70b-versatile"} />
        )}
        <Button onClick={() => { setOther(false); load(); }} busy={loading} disabled={!apiKey && !hasSavedKey} className="shrink-0">
          {models ? "Refresh" : "Load models"}
        </Button>
      </div>
      {error && <span className="mt-1 block text-xs text-red-600">{error}</span>}
      {models && value && !listed && !other && (
        <span className="mt-1 block text-xs text-amber-700">“{value}” is not available to this key; pick one from the list.</span>
      )}
    </Field>
  );
}

function FreeKeyHelp({ provider, onUseGroq }: { provider: string; onUseGroq: () => void }) {
  if (provider === "gemini")
    return (
      <div className="mb-4 rounded-xl border border-emerald-200 bg-emerald-50/70 p-3.5 text-sm text-slate-700">
        <p className="font-medium text-emerald-900">No API key yet? Get a free Gemini key (about 1 minute, no card)</p>
        <ol className="mt-1.5 list-decimal space-y-0.5 pl-5 text-xs">
          <li>Open Google AI Studio and sign in with your Google account.</li>
          <li>Click <b>Create API key</b>. If a billing or payment screen appears, close it: the free tier needs no card.</li>
          <li>Copy the key, paste it below, pick the recommended model, then <b>Save</b> and <b>Test</b>.</li>
        </ol>
        <div className="mt-2.5 flex flex-wrap gap-2">
          <a href="https://aistudio.google.com/apikey" target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-emerald-700">
            Get a free Gemini key <ExternalLink className="size-3.5" aria-hidden />
          </a>
          <button type="button" onClick={onUseGroq} className="rounded-lg border border-emerald-300 bg-white px-3 py-1.5 text-xs font-medium text-emerald-800 hover:bg-emerald-50">
            Or use Groq instead (also free)
          </button>
        </div>
        <p className="mt-2 text-[0.6875rem] text-slate-500">On Google's free tier, prompts (including resume text) may be used to improve Google's products.</p>
      </div>
    );
  if (provider === "openai_compatible")
    return (
      <div className="mb-4 rounded-xl border border-emerald-200 bg-emerald-50/70 p-3.5 text-sm text-slate-700">
        <p className="font-medium text-emerald-900">Free option: Groq (no card)</p>
        <p className="mt-1 text-xs">Sign in at Groq with Google, open <b>API Keys → Create API Key</b>, paste it below. The base URL is filled in for you.</p>
        <a href="https://console.groq.com/keys" target="_blank" rel="noopener noreferrer" className="mt-2 inline-flex items-center gap-1.5 rounded-lg bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-emerald-700">
          Get a free Groq key <ExternalLink className="size-3.5" aria-hidden />
        </a>
      </div>
    );
  return null;
}

export function LlmForm({ view, actions }: { view: IntegrationView; actions: ConnectionActions }) {
  const c = view.config;
  const saved = str(c.provider);
  const [provider, setProvider] = useState(saved || "gemini");
  const [endpoint, setEndpoint] = useState(str(c.endpoint));
  const [deployment, setDeployment] = useState(str(c.deployment));
  const [apiVersion, setApiVersion] = useState(str(c.api_version) || "2025-04-01-preview");
  const [baseUrl, setBaseUrl] = useState(str(c.base_url));
  const [model, setModel] = useState(str(c.model));
  const [temperature, setTemperature] = useState<number | null>((c.temperature as number | null) ?? null);
  const [apiKey, setApiKey] = useState("");
  const hasSavedKey = view.secrets_set.includes("api_key") && provider === saved;
  const save = () => {
    const config =
      provider === "azure_openai"
        ? { provider, endpoint, deployment, api_version: apiVersion, temperature }
        : provider === "openai_compatible"
          ? { provider, base_url: baseUrl || null, model, temperature }
          : { provider, model, temperature };
    actions.save(config, { api_key: apiKey });
    setApiKey("");
  };
  const useGroq = () => {
    setProvider("openai_compatible");
    setBaseUrl(GROQ_URL);
    setModel("");
  };
  return (
    <Card title={<span className="flex flex-wrap items-center gap-2">AI provider <StatusBadges view={view} />{view.verified_this_session && <Badge tone="green">test passed</Badge>}</span>}>
      <p className="mb-3 text-sm text-slate-600">
        Optional. Lets the assistant understand free-form requests and improves resume and email wording; every AI change is fact-checked against your resume. Everything else works without it.
      </p>
      {!(view.configured && provider === saved) && <FreeKeyHelp provider={provider} onUseGroq={useGroq} />}
      <div className="grid gap-3 md:grid-cols-2">
        <Field label="Provider">
          <Select
            value={provider}
            onChange={(e) => {
              setProvider(e.target.value);
              setModel(e.target.value === saved ? str(c.model) : "");
            }}
          >
            {Object.entries(LLM_PROVIDERS).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </Select>
        </Field>
        <SecretInput label="API key" name="api_key" view={view} value={apiKey} onChange={setApiKey} />
        {provider === "azure_openai" && (
          <>
            <Field label="Endpoint" hint="https://<resource>.openai.azure.com or https://<resource>.services.ai.azure.com">
              <TextInput value={endpoint} onChange={(e) => setEndpoint(e.target.value)} />
            </Field>
            <Field label="Deployment name" hint="e.g. gpt-5.1">
              <TextInput value={deployment} onChange={(e) => setDeployment(e.target.value)} />
            </Field>
            <Field label="API version">
              <TextInput value={apiVersion} onChange={(e) => setApiVersion(e.target.value)} />
            </Field>
          </>
        )}
        {provider === "openai_compatible" && (
          <Field label="Base URL" hint={<>Blank for api.openai.com; https only. <button type="button" className="text-indigo-700 underline" onClick={() => setBaseUrl(GROQ_URL)}>Use Groq</button></>}>
            <TextInput value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="https://api.openai.com/v1" />
          </Field>
        )}
        {(provider === "gemini" || provider === "openai_compatible") && (
          <ModelPicker provider={provider} apiKey={apiKey} baseUrl={baseUrl} hasSavedKey={hasSavedKey} value={model} onChange={setModel} />
        )}
        <Field label="Temperature" hint="Leave blank (recommended). Some reasoning models reject it.">
          <NumberInput value={temperature} step={0.1} min={0} max={2} onChange={setTemperature} />
        </Field>
      </div>
      <Actions a={actions} onSave={save} view={view} />
    </Card>
  );
}

export function AdzunaForm({ view, actions }: { view: IntegrationView; actions: ConnectionActions }) {
  const [appId, setAppId] = useState(str(view.config.app_id));
  const [appKey, setAppKey] = useState("");
  return (
    <Card title={<span className="flex flex-wrap items-center gap-2">Adzuna job search <StatusBadges view={view} /></span>}>
      <p className="mb-3 text-sm text-slate-600">
        Optional keyword search across Indian job listings. Get a free key at developer.adzuna.com, then enable the Adzuna source below.
      </p>
      <SetupGuide
        open={!view.configured}
        title="How to get a free Adzuna key (about 2 minutes, no card)"
        steps={[
          <>Sign up on the Adzuna developer site and confirm your email.</>,
          <>Open <b>Dashboard → API Access Details</b> and copy the <b>Application ID</b> and <b>Application Key</b>.</>,
          <>Paste them below, click <b>Save</b>, then turn on the <b>Adzuna</b> source under Job sources.</>,
        ]}
        links={[{ label: "Sign up at Adzuna developer", href: "https://developer.adzuna.com/signup" }]}
      />
      <div className="grid gap-3 md:grid-cols-2">
        <Field label="App ID">
          <TextInput value={appId} onChange={(e) => setAppId(e.target.value)} />
        </Field>
        <SecretInput label="App key" name="app_key" view={view} value={appKey} onChange={setAppKey} />
      </div>
      <Actions
        a={actions}
        view={view}
        onSave={() => {
          actions.save({ app_id: appId }, { app_key: appKey });
          setAppKey("");
        }}
      />
    </Card>
  );
}

export function ImapForm({ view, actions }: { view: IntegrationView; actions: ConnectionActions }) {
  const c = view.config;
  const [host, setHost] = useState(str(c.host) || "imap.gmail.com");
  const [username, setUsername] = useState(str(c.username));
  const [folder, setFolder] = useState(str(c.folder) || "INBOX");
  const [password, setPassword] = useState("");
  return (
    <Card title={<span className="flex flex-wrap items-center gap-2">Job-alert mailbox (LinkedIn, Naukri, Indeed, Hirist) <StatusBadges view={view} /></span>}>
      <p className="mb-3 text-sm text-slate-600">
        These sites have no job-search API, but they email you job alerts. The agent reads only those alert emails from the last few
        days, <strong>read-only</strong>: nothing is marked read, moved or deleted, and other mail is never opened. Create alerts on the
        sites, connect the mailbox here, then enable the job-alerts source below.
      </p>
      <SetupGuide
        open={!view.configured}
        title="How to set this up with Gmail"
        steps={[
          <>Create job alerts for your roles and cities on each site you use (links below). Use the <b>same email address</b> as this mailbox.</>,
          ...APP_PASSWORD_STEPS,
          <>If Gmail asks, make sure IMAP is on: Gmail → Settings → See all settings → <b>Forwarding and POP/IMAP</b>.</>,
          <>Click <b>Fill in Gmail settings</b>, enter your Gmail address as <b>Username</b>, paste the app password, and click <b>Save</b>. Then turn on the <b>Job alerts</b> source below.</>,
        ]}
        links={[
          ...GOOGLE_LINKS,
          { label: "LinkedIn job alerts", href: "https://www.linkedin.com/jobs/" },
          { label: "Naukri job alerts", href: "https://www.naukri.com/" },
          { label: "Indeed job alerts", href: "https://in.indeed.com/" },
          { label: "Hirist", href: "https://www.hirist.tech/" },
        ]}
        actions={<FillButton onClick={() => { setHost("imap.gmail.com"); setFolder("INBOX"); }}>Fill in Gmail settings</FillButton>}
        note="On each site, search for your role and city, then choose “Set alert”, “Create job alert” or “Get new jobs by email”."
      />
      <div className="grid gap-3 md:grid-cols-2">
        <Field label="IMAP host" hint="Gmail: imap.gmail.com · Outlook: outlook.office365.com">
          <TextInput value={host} onChange={(e) => setHost(e.target.value)} />
        </Field>
        <Field label="Port" hint="IMAP over TLS only">
          <TextInput value="993" disabled readOnly />
        </Field>
        <Field label="Username" hint="Usually your full email address">
          <TextInput value={username} autoComplete="off" onChange={(e) => setUsername(e.target.value)} />
        </Field>
        <Field label="Folder" hint="Where the alerts arrive">
          <TextInput value={folder} onChange={(e) => setFolder(e.target.value)} />
        </Field>
        <SecretInput label="Password" name="password" view={view} value={password} onChange={setPassword}
          hint="For Gmail, an App Password (myaccount.google.com/apppasswords), never your account password." />
      </div>
      <Actions
        a={actions}
        view={view}
        onSave={() => {
          actions.save({ host, port: 993, username, folder: folder || "INBOX" }, { password });
          setPassword("");
        }}
      />
    </Card>
  );
}

export function JoobleForm({ view, actions }: { view: IntegrationView; actions: ConnectionActions }) {
  const [apiKey, setApiKey] = useState("");
  return (
    <Card title={<span className="flex flex-wrap items-center gap-2">Jooble job search <StatusBadges view={view} /></span>}>
      <p className="mb-3 text-sm text-slate-600">
        Optional keyword search across many Indian job sites. Request a free key at jooble.org/api/about, then enable the Jooble source below.
      </p>
      <SetupGuide
        open={!view.configured}
        title="How to get a free Jooble key"
        steps={[
          <>Open Jooble's API page and fill in the short request form with your email.</>,
          <>Jooble emails you the key, usually within a day.</>,
          <>Paste it below, click <b>Save</b>, then turn on the <b>Jooble</b> source under Job sources.</>,
        ]}
        links={[{ label: "Request a Jooble key", href: "https://jooble.org/api/about" }]}
      />
      <div className="grid gap-3 md:grid-cols-2">
        <SecretInput label="API key" name="api_key" view={view} value={apiKey} onChange={setApiKey} />
      </div>
      <Actions
        a={actions}
        view={view}
        onSave={() => {
          actions.save({}, { api_key: apiKey });
          setApiKey("");
        }}
      />
    </Card>
  );
}

export function WebSearchForm({ view, actions }: { view: IntegrationView; actions: ConnectionActions }) {
  const [provider, setProvider] = useState(String(view.config.provider ?? "tavily"));
  const [apiKey, setApiKey] = useState("");
  return (
    <Card title={<span className="flex flex-wrap items-center gap-2">Web search for the assistant <StatusBadges view={view} /></span>}>
      <p className="mb-3 text-sm text-slate-600">
        Optional. Lets the assistant search the live web for new postings on company career pages and Greenhouse, Lever, Ashby and SmartRecruiters boards, through a licensed search API with your own key. Search
        engines are never scraped.
      </p>
      <SetupGuide
        open={!view.configured}
        title="How to get a free web-search key (about 1 minute)"
        steps={[
          <><b>Tavily</b> (recommended): sign in with Google, and your API key is shown on the home page. The free plan gives a monthly allowance of searches with no card.</>,
          <>Choose the provider below, paste the key, click <b>Save</b>, then <b>Test</b>.</>,
          <><b>Brave Search API</b> also works, but may ask for a card to activate its free plan.</>,
        ]}
        links={[
          { label: "Get a free Tavily key", href: "https://app.tavily.com/" },
          { label: "Brave Search API", href: "https://api-dashboard.search.brave.com/" },
        ]}
      />
      <div className="grid gap-3 md:grid-cols-2">
        <Field label="Provider">
          <Select value={provider} onChange={(e) => setProvider(e.target.value)}>
            <option value="tavily">Tavily (free, no card)</option>
            <option value="brave">Brave Search API</option>
          </Select>
        </Field>
        <SecretInput label="API key" name="api_key" view={view} value={apiKey} onChange={setApiKey} />
      </div>
      <Actions
        a={actions}
        view={view}
        onSave={() => {
          actions.save({ provider }, { api_key: apiKey });
          setApiKey("");
        }}
      />
    </Card>
  );
}

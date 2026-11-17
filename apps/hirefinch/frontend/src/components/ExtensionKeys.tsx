// Account → Browser extension: install the autofill extension, connect it in one click, manage its keys.
import { useQuery } from "@tanstack/react-query";
import { Check, CheckCircle2, Copy, Download, KeyRound, Link2, RefreshCw, Smartphone } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import { Alert, Badge, Button, Card, Empty, ErrorText, TextInput, formatDate, useAction } from "./ui";

interface ExtensionKey {
  id: number;
  name: string;
  prefix: string;
  created_at: string;
  expires_at: string;
  last_used_at: string | null;
}

// Fixed by the public "key" in extension/manifest.json; the site may only talk to it from the
// addresses listed under externally_connectable there.
export const EXTENSION_ID = "mfjnlkfheocdimmakkekkoioaclollpf";

type ExtensionState = { installed: false } | { installed: true; version: string; connected: boolean };

interface ChromeRuntime {
  sendMessage: (id: string, msg: unknown, reply: (r: unknown) => void) => void;
  lastError?: unknown;
}

function runtime(): ChromeRuntime | undefined {
  return (window as unknown as { chrome?: { runtime?: ChromeRuntime } }).chrome?.runtime;
}

function message<T>(msg: unknown): Promise<T | undefined> {
  const rt = runtime();
  if (!rt?.sendMessage) return Promise.resolve(undefined); // Chrome exposes this only when the extension is installed
  return new Promise((resolve) => {
    try {
      rt.sendMessage(EXTENSION_ID, msg, (r) => resolve(rt.lastError ? undefined : (r as T)));
    } catch {
      resolve(undefined);
    }
  });
}

export const isPhone = () => /Android|iPhone|iPad|iPod|Mobile/i.test(navigator.userAgent);

function useExtensionState() {
  const [state, setState] = useState<ExtensionState | null>(null);
  const check = useCallback(async () => {
    const r = await message<{ installed: boolean; version: string; connected: boolean }>({ type: "ping" });
    setState(r?.installed ? { installed: true, version: r.version, connected: r.connected } : { installed: false });
  }, []);
  useEffect(() => {
    void check();
    // Coming back from chrome://extensions or the extension's settings tab refreshes the status.
    window.addEventListener("focus", check);
    return () => window.removeEventListener("focus", check);
  }, [check]);
  return { state, check };
}

function CopyText({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      className="inline-flex items-center gap-1 rounded-md bg-slate-100 px-1.5 py-0.5 font-mono text-xs text-slate-800 hover:bg-slate-200"
      onClick={async () => {
        await navigator.clipboard.writeText(text).catch(() => undefined);
        setCopied(true);
      }}
      aria-label={`Copy ${text}`}
    >
      {text} {copied ? <Check className="size-3 text-emerald-600" /> : <Copy className="size-3" />}
    </button>
  );
}

function Step({ n, done, title, children }: { n: number; done: boolean; title: string; children: React.ReactNode }) {
  return (
    <li className="flex gap-3">
      <span
        className={`grid size-6 shrink-0 place-items-center rounded-full text-xs font-semibold ${done ? "bg-emerald-100 text-emerald-700" : "bg-indigo-100 text-indigo-700"}`}
      >
        {done ? <Check className="size-3.5" aria-label="done" /> : n}
      </span>
      <div className="min-w-0 flex-1 text-sm text-slate-700">
        <p className="font-medium text-slate-900">{title}</p>
        {children}
      </div>
    </li>
  );
}

export function ExtensionKeys() {
  const keys = useQuery({ queryKey: ["extension-keys"], queryFn: () => api<ExtensionKey[]>("/account/extension-tokens") });
  const { state, check } = useExtensionState();
  const [sent, setSent] = useState(false);
  const installed = state?.installed === true;
  const connected = state?.installed === true && state.connected;

  const connect = useAction(
    () => api<ExtensionKey & { token: string }>("/account/extension-tokens", { method: "POST", body: { name: `Chrome, connected ${new Date().toLocaleDateString()}` } }),
    async (r) => {
      const reply = await message<{ opened: boolean }>({ type: "connect", token: r.token });
      setSent(!!reply?.opened);
    },
  );

  return (
    <Card title="Browser extension: fill application forms" className="lg:col-span-2">
      <p className="mb-3 text-sm text-slate-600">
        Applies on employer sites (Greenhouse, Lever, Ashby…) for you: it fills your details and prepared answers, attaches the resume tailored for the job, and submits only when every
        required field is filled and no CAPTCHA shows (after a 5-second countdown you can cancel). It never answers gender, diversity or legal questions and doesn't run on LinkedIn or
        Naukri.
      </p>

      {isPhone() ? (
        <Alert tone="info">
          <p className="flex items-center gap-1.5 font-medium">
            <Smartphone className="size-4" aria-hidden /> Phone browsers can't run extensions
          </p>
          <p className="mt-1">
            Set this up on a laptop with Chrome or Edge. On your phone, apply from the <b>Application Queue</b>: open an application, copy each prepared answer with one tap, and paste
            it into the employer's form.
          </p>
        </Alert>
      ) : (
        <>
          <div className="mb-4 flex flex-wrap items-center gap-2 text-sm">
            <span className="text-slate-600">Status:</span>
            {state === null ? (
              <Badge>checking…</Badge>
            ) : connected ? (
              <Badge tone="green">connected · v{state.version}</Badge>
            ) : installed ? (
              <Badge tone="amber">installed, not connected yet</Badge>
            ) : (
              <Badge>not installed</Badge>
            )}
            <Button variant="ghost" onClick={() => void check()} className="text-xs">
              <RefreshCw className="size-3.5" aria-hidden /> Check again
            </Button>
          </div>

          {connected ? (
            <Alert tone="success">
              <p className="flex items-center gap-1.5 font-medium">
                <CheckCircle2 className="size-4" aria-hidden /> All set
              </p>
              <p className="mt-1">
                In the Application Queue, click <b>Auto-apply with the extension</b>. On other career sites, open the form and click the HireFinch icon → <b>Fill and submit if certain</b>.
              </p>
            </Alert>
          ) : (
            <ol className="space-y-4">
              <Step n={1} done={installed} title="Download and unzip">
                <a href="/hirefinch-extension.zip" download className="mt-1 inline-flex items-center gap-1 font-medium text-indigo-700 hover:underline">
                  <Download className="size-3.5" aria-hidden /> hirefinch-extension.zip
                </a>
                <p className="mt-0.5 text-xs text-slate-500">Then right-click it → Extract all (Windows) or double-click it (Mac). Keep the folder: Chrome runs it from there.</p>
              </Step>
              <Step n={2} done={installed} title="Add it to Chrome or Edge">
                <p className="mt-1">
                  Open a new tab and paste <CopyText text="chrome://extensions" /> (Edge: <CopyText text="edge://extensions" />).
                </p>
                <p className="mt-1">
                  Turn on <b>Developer mode</b> (top right), click <b>Load unpacked</b>, and choose the unzipped folder.
                </p>
                <p className="mt-1 text-xs text-slate-500">Had an older HireFinch or Job Agent extension? Remove it there first.</p>
              </Step>
              <Step n={3} done={false} title="Connect it to your account">
                {sent ? (
                  <p className="mt-1">
                    The extension opened its settings tab: check the address and click <b>Connect</b>. Then come back here.
                  </p>
                ) : (
                  <>
                    <Button variant="primary" className="mt-1.5" busy={connect.isPending} disabled={!installed} onClick={() => connect.mutate()}>
                      <Link2 className="size-4" aria-hidden /> Connect extension
                    </Button>
                    {!installed && state !== null && <p className="mt-1 text-xs text-slate-500">Finish step 2 first; this page notices when you come back.</p>}
                  </>
                )}
                <ErrorText error={connect.error} />
              </Step>
            </ol>
          )}
        </>
      )}

      <details className="mt-5 border-t border-slate-100 pt-3 text-sm">
        <summary className="cursor-pointer text-slate-600">Keys and manual setup</summary>
        <ManualKeys keys={keys.data} />
      </details>
    </Card>
  );
}

function ManualKeys({ keys }: { keys: ExtensionKey[] | undefined }) {
  const [name, setName] = useState("Chrome on my laptop");
  const [fresh, setFresh] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const create = useAction(() => api<ExtensionKey & { token: string }>("/account/extension-tokens", { method: "POST", body: { name } }), (r) => {
    setFresh(r.token);
    setCopied(false);
  });
  const revoke = useAction((id: number) => api(`/account/extension-tokens/${id}`, { method: "DELETE" }));

  return (
    <div className="mt-3">
      <p className="mb-2 text-slate-600">
        To connect by hand, create a key and paste it, with this site's address ({window.location.origin}), into the extension's settings.
      </p>
      {fresh ? (
        <Alert tone="success">
          <p className="font-medium">Your new key. Copy it now: it is shown only once.</p>
          <div className="mt-2 flex gap-2">
            <code className="min-w-0 flex-1 break-all rounded-lg bg-white px-2 py-1.5 text-xs text-slate-800 ring-1 ring-emerald-200">{fresh}</code>
            <Button
              aria-label="Copy key"
              onClick={async () => {
                await navigator.clipboard.writeText(fresh).catch(() => undefined);
                setCopied(true);
              }}
            >
              {copied ? <Check className="size-4" /> : <Copy className="size-4" />}
            </Button>
          </div>
          <button type="button" className="mt-2 text-xs text-emerald-800 underline" onClick={() => setFresh(null)}>
            Done
          </button>
        </Alert>
      ) : (
        <div className="flex gap-2">
          <TextInput aria-label="Key name" value={name} maxLength={60} onChange={(e) => setName(e.target.value)} />
          <Button busy={create.isPending} disabled={!name.trim()} onClick={() => create.mutate()} className="shrink-0">
            <KeyRound className="size-4" aria-hidden /> Create key
          </Button>
        </div>
      )}
      <ErrorText error={create.error || revoke.error} />
      <h3 className="mb-1 mt-4 text-sm font-semibold">Active keys</h3>
      {keys?.length ? (
        <ul className="divide-y divide-slate-100">
          {keys.map((k) => (
            <li key={k.id} className="flex flex-wrap items-center gap-2 py-2">
              <span className="font-medium">{k.name}</span>
              <code className="text-xs text-slate-500">{k.prefix}…</code>
              <span className="text-xs text-slate-500">
                {k.last_used_at ? `used ${formatDate(k.last_used_at, true)}` : "never used"} · expires {formatDate(k.expires_at)}
              </span>
              <Button variant="ghost" className="ml-auto text-red-600" busy={revoke.isPending && revoke.variables === k.id} onClick={() => revoke.mutate(k.id)}>
                Revoke
              </Button>
            </li>
          ))}
        </ul>
      ) : (
        <Empty>No keys yet.</Empty>
      )}
    </div>
  );
}

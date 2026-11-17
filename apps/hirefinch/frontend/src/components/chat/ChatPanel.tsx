import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowUp, Bot, Maximize2, Plus, Sparkles } from "lucide-react";
import { Fragment, useEffect, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router";
import { api } from "../../api/client";
import { cx } from "../ui";
import { ActionCard, CardView } from "./Cards";
import type { AssistantStatus, ChatAction, ChatMessage, Conversation, ConversationDetail } from "./types";

const STARTERS = [
  "Show my best matches posted this week",
  "Find backend jobs in Pune",
  "What's my application status?",
  "What's missing in my profile?",
];

/** Text with "- " bullets, links for https URLs and #ids for jobs. Built from React elements only. */
function RichText({ text }: { text: string }) {
  const inline = (line: string, key: number): ReactNode => {
    const parts = line.split(/(https:\/\/[^\s<>"')]+|#\d{1,9}\b|\*\*[^*]+\*\*)/g);
    return (
      <Fragment key={key}>
        {parts.map((p, i) => {
          if (p.startsWith("https://"))
            return (
              <a key={i} href={p} target="_blank" rel="noopener noreferrer nofollow" className="break-all text-indigo-700 underline decoration-indigo-200 hover:decoration-indigo-500">
                {p}
              </a>
            );
          if (/^#\d+$/.test(p))
            return (
              <Link key={i} to={`/jobs/${p.slice(1)}`} className="font-medium text-indigo-700 hover:underline">
                {p}
              </Link>
            );
          if (p.startsWith("**") && p.endsWith("**")) return <strong key={i}>{p.slice(2, -2)}</strong>;
          return p;
        })}
      </Fragment>
    );
  };
  const blocks: ReactNode[] = [];
  let bullets: string[] = [];
  const flush = () => {
    if (bullets.length) blocks.push(<ul key={`u${blocks.length}`} className="my-1 list-disc space-y-0.5 pl-5">{bullets.map((b, i) => <li key={i}>{inline(b, i)}</li>)}</ul>);
    bullets = [];
  };
  text.split("\n").forEach((line, i) => {
    const t = line.trim();
    if (/^[-•*]\s+/.test(t)) bullets.push(t.replace(/^[-•*]\s+/, ""));
    else {
      flush();
      if (t) blocks.push(<p key={`p${i}`}>{inline(t, i)}</p>);
    }
  });
  flush();
  return <div className="space-y-1.5">{blocks}</div>;
}

function Typing() {
  return (
    <div className="flex items-center gap-1 px-1 py-2" aria-label="Assistant is typing">
      {[0, 150, 300].map((d) => (
        <span key={d} className="typing-dot size-1.5 rounded-full bg-slate-400" style={{ animationDelay: `${d}ms` }} />
      ))}
    </div>
  );
}

function Avatar() {
  return (
    <span className="grid size-8 shrink-0 place-items-center rounded-full bg-gradient-to-br from-indigo-500 to-violet-600 shadow-sm">
      <Sparkles className="size-4 text-white" aria-hidden />
    </span>
  );
}

export function ChatPanel({
  conversationId,
  onConversation,
  compact = false,
  onExpand,
  initialPrompt,
}: {
  initialPrompt?: string;
  conversationId?: number | null;
  onConversation?: (id: number) => void;
  compact?: boolean;
  onExpand?: () => void;
}) {
  const client = useQueryClient();
  const status = useQuery({ queryKey: ["assistant-status"], queryFn: () => api<AssistantStatus>("/assistant/status"), staleTime: 60_000 });
  const list = useQuery({ queryKey: ["conversations"], queryFn: () => api<Conversation[]>("/assistant/conversations"), enabled: conversationId === undefined });
  // Controlled by the page, or (in the floating panel) the most recent conversation.
  const [localId, setLocalId] = useState<number | "new" | null>(null);
  const cid = conversationId !== undefined ? conversationId : localId === "new" ? null : localId ?? list.data?.[0]?.id ?? null;
  const detail = useQuery({ queryKey: ["conversation", cid], queryFn: () => api<ConversationDetail>(`/assistant/conversations/${cid}`), enabled: cid !== null });
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [pending, setPending] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [text, setText] = useState("");
  const [actionBusy, setActionBusy] = useState<number | null>(null);
  const bottom = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const max = status.data?.max_chars ?? 2000;

  useEffect(() => {
    setMessages(cid === null ? [] : detail.data?.messages ?? []);
  }, [cid, detail.data]);
  // Braces matter: newer Chrome returns a Promise from scrollIntoView, and React would call it as a cleanup.
  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages.length, pending]);
  const asked = useRef(false);
  useEffect(() => {
    if (initialPrompt && !asked.current && cid === null) {
      asked.current = true; // once, even under StrictMode double effects
      void send(initialPrompt);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialPrompt]);

  const setAction = (a: ChatAction) => setMessages((ms) => ms.map((m) => (m.action?.id === a.id ? { ...m, action: a } : m)));

  async function send(raw: string) {
    const value = raw.trim();
    if (!value || pending) return;
    setError(null);
    setPending(value);
    setText("");
    try {
      let id = cid;
      const created = id === null;
      if (id === null) id = (await api<Conversation>("/assistant/conversations", { method: "POST" })).id;
      const r = await api<{ messages: ChatMessage[] }>(`/assistant/conversations/${id}/messages`, { method: "POST", body: { text: value } });
      setMessages((ms) => [...ms, ...r.messages]);
      if (created) {
        setLocalId(id);
        onConversation?.(id); // after the reply, so a remount loads the saved messages
      }
      client.invalidateQueries({ queryKey: ["conversations"] });
      // Actions in chat change jobs, applications and the profile shown on other pages.
      client.invalidateQueries({ predicate: (q) => !["conversation", "conversations", "assistant-status", "auth"].includes(String(q.queryKey[0])) });
    } catch (e) {
      setError((e as Error).message);
      setText(value);
    } finally {
      setPending(null);
      input.current?.focus();
    }
  }

  async function decide(a: ChatAction, confirm: boolean) {
    setActionBusy(a.id);
    setError(null);
    try {
      const r = await api<{ action: ChatAction; messages?: ChatMessage[] }>(`/assistant/actions/${a.id}/${confirm ? "confirm" : "cancel"}`, { method: "POST" });
      setAction(r.action);
      if (r.messages) setMessages((ms) => [...ms, ...r.messages!]);
      client.invalidateQueries({ predicate: (q) => !["conversation", "conversations", "assistant-status", "auth"].includes(String(q.queryKey[0])) });
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setActionBusy(null);
    }
  }

  const last = messages[messages.length - 1];
  const empty = messages.length === 0 && !pending;

  return (
    <div className="flex h-full min-h-0 flex-col bg-white">
      <header className="flex items-center gap-3 border-b border-slate-100 px-4 py-3">
        <Avatar />
        <div className="min-w-0 flex-1 leading-tight">
          <p className="font-semibold tracking-tight text-slate-900">Job Assistant</p>
          <p className="flex items-center gap-1.5 truncate text-xs text-slate-500">
            <span className={cx("size-1.5 rounded-full", status.data?.ai ? "bg-emerald-500" : "bg-amber-400")} aria-hidden />
            {status.data?.ai ? "AI ready" : "Quick mode: connect AI in Integrations to chat freely"}
            {status.data?.web_search ? " · web search on" : ""}
          </p>
        </div>
        {compact && (
          <>
            <button
              type="button"
              aria-label="New chat"
              title="New chat"
              onClick={() => setLocalId("new")}
              className="rounded-lg p-1.5 text-slate-500 hover:bg-slate-100"
            >
              <Plus className="size-4" />
            </button>
            {onExpand && (
              <button type="button" aria-label="Open full screen" title="Open full screen" onClick={onExpand} className="rounded-lg p-1.5 text-slate-500 hover:bg-slate-100">
                <Maximize2 className="size-4" />
              </button>
            )}
          </>
        )}
      </header>

      <div className="scroll-soft min-h-0 flex-1 overflow-y-auto bg-gradient-to-b from-slate-50/80 to-white px-4 py-4" aria-live="polite">
        {empty ? (
          <div className="mx-auto flex max-w-xl flex-col items-center pt-6 text-center">
            <span className="grid size-14 place-items-center rounded-2xl bg-gradient-to-br from-indigo-500 to-violet-600 shadow-lift">
              <Bot className="size-7 text-white" aria-hidden />
            </span>
            <h2 className="mt-4 text-lg font-semibold tracking-tight text-slate-900">Hi! I'm your job assistant.</h2>
            <p className="mt-1 text-sm text-slate-500">
              I find jobs that match your resume, explain the fit, apply for you after you confirm, and write to recruiters. Paste a job link to import it.
            </p>
            <div className={cx("mt-5 grid w-full gap-2", !compact && "sm:grid-cols-2")}>
              {STARTERS.map((s) => (
                <button key={s} type="button" onClick={() => send(s)} className="rounded-xl border border-slate-200 bg-white px-3.5 py-2.5 text-left text-sm text-slate-700 shadow-xs transition hover:border-indigo-300 hover:bg-indigo-50/50">
                  {s}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className={cx("mx-auto space-y-4", !compact && "max-w-3xl")}>
            {messages.map((m) =>
              m.role === "user" ? (
                <div key={m.id} className="rise-in flex justify-end">
                  <p className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-md bg-gradient-to-br from-indigo-500 to-indigo-600 px-3.5 py-2 text-sm text-white shadow-sm">{m.content}</p>
                </div>
              ) : (
                <div key={m.id} className="rise-in flex gap-2.5">
                  <Avatar />
                  <div className="min-w-0 flex-1 space-y-2.5">
                    <div className="w-fit max-w-full rounded-2xl rounded-tl-md bg-white px-3.5 py-2.5 text-sm leading-relaxed text-slate-800 shadow-xs ring-1 ring-slate-200/70">
                      <RichText text={m.content} />
                    </div>
                    {m.cards.map((c, i) => (
                      <CardView key={i} card={c} send={send} busy={!!pending} />
                    ))}
                    {m.action && <ActionCard action={m.action} busy={actionBusy === m.action.id} onConfirm={() => decide(m.action!, true)} onCancel={() => decide(m.action!, false)} />}
                    {m === last && m.suggestions.length > 0 && !pending && (
                      <div className="flex flex-wrap gap-1.5">
                        {m.suggestions.map((s) => (
                          <button key={s} type="button" onClick={() => send(s)} className="rounded-full border border-indigo-200 bg-white px-3 py-1 text-xs font-medium text-indigo-700 transition hover:bg-indigo-50">
                            {s}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              ),
            )}
            {pending && (
              <>
                <div className="flex justify-end">
                  <p className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-md bg-indigo-500/80 px-3.5 py-2 text-sm text-white">{pending}</p>
                </div>
                <div className="flex gap-2.5">
                  <Avatar />
                  <div className="rounded-2xl rounded-tl-md bg-white px-3 shadow-xs ring-1 ring-slate-200/70">
                    <Typing />
                  </div>
                </div>
              </>
            )}
          </div>
        )}
        <div ref={bottom} />
      </div>

      <form
        className="border-t border-slate-100 bg-white p-3 pb-[max(0.75rem,env(safe-area-inset-bottom))]"
        onSubmit={(e) => {
          e.preventDefault();
          send(text);
        }}
      >
        {error && <p role="alert" className="mb-2 rounded-lg bg-red-50 px-3 py-1.5 text-xs text-red-700">{error}</p>}
        <div className={cx("mx-auto flex items-end gap-2 rounded-2xl border border-slate-200 bg-white p-1.5 shadow-xs transition focus-within:border-indigo-400 focus-within:ring-4 focus-within:ring-indigo-500/10", !compact && "max-w-3xl")}>
          <textarea
            ref={input}
            rows={1}
            value={text}
            maxLength={max}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send(text);
              }
            }}
            placeholder={compact ? "Ask or paste a job link…" : "Ask anything, or paste a job link…"}
            aria-label="Message"
            className="max-h-40 min-h-9 flex-1 resize-none bg-transparent px-2 py-1.5 text-sm text-slate-900 placeholder:text-slate-400 focus:outline-none"
          />
          <button type="submit" aria-label="Send" disabled={!text.trim() || !!pending} className="grid size-9 shrink-0 place-items-center rounded-xl bg-gradient-to-br from-indigo-500 to-indigo-600 text-white shadow-sm transition hover:to-indigo-700 disabled:opacity-40">
            <ArrowUp className="size-4" />
          </button>
        </div>
        <p className="mx-auto mt-1.5 max-w-3xl px-1 text-[0.6875rem] text-slate-400">
          Applying, sending email and changing your profile always wait for your confirmation.
          {text.length > max * 0.8 && ` ${text.length}/${max}`}
        </p>
      </form>
    </div>
  );
}

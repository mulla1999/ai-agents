import { useQuery, useQueryClient } from "@tanstack/react-query";
import { MessageSquare, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { useSearchParams } from "react-router";
import { api } from "../api/client";
import { ChatPanel } from "../components/chat/ChatPanel";
import type { Conversation } from "../components/chat/types";
import { cx, formatDate } from "../components/ui";

export function AssistantPage() {
  const client = useQueryClient();
  const [params, setParams] = useSearchParams();
  const list = useQuery({ queryKey: ["conversations"], queryFn: () => api<Conversation[]>("/assistant/conversations") });
  const selected = params.get("c");
  const prompt = params.get("q");
  const cid = selected === "new" ? null : selected ? Number(selected) : list.data?.[0]?.id ?? null;
  const open = (id: number | "new") => setParams({ c: String(id) }, { replace: true });
  const [sheet, setSheet] = useState(false);
  const remove = async (id: number) => {
    if (!window.confirm("Delete this chat? This cannot be undone.")) return;
    await api(`/assistant/conversations/${id}`, { method: "DELETE" });
    await client.invalidateQueries({ queryKey: ["conversations"] });
    if (id === cid) open("new");
  };

  return (
    <div className="flex h-[calc(100vh-3.5rem)] overflow-hidden bg-white supports-[height:100dvh]:h-[calc(100dvh-3.5rem)] md:h-[calc(100vh-2rem)] md:rounded-2xl md:shadow-soft md:ring-1 md:ring-slate-200/80 md:supports-[height:100dvh]:h-[calc(100dvh-2rem)]">
      <aside className="hidden w-72 shrink-0 flex-col border-r border-slate-100 bg-slate-50/60 lg:flex">
        <div className="p-3">
          <button
            type="button"
            onClick={() => open("new")}
            className="flex w-full items-center justify-center gap-2 rounded-xl bg-gradient-to-b from-indigo-500 to-indigo-600 px-3 py-2.5 text-sm font-medium text-white shadow-sm transition hover:to-indigo-700"
          >
            <Plus className="size-4" aria-hidden /> New chat
          </button>
        </div>
        <p className="px-4 pb-1 text-[0.6875rem] font-semibold uppercase tracking-wider text-slate-400">Recent</p>
        <ul className="scroll-soft min-h-0 flex-1 space-y-0.5 overflow-y-auto px-2 pb-3">
          {(list.data ?? []).map((c) => (
            <li key={c.id} className="group relative">
              <button
                type="button"
                onClick={() => open(c.id)}
                className={cx("flex w-full items-start gap-2.5 rounded-lg px-2.5 py-2 text-left transition", c.id === cid ? "bg-white shadow-xs ring-1 ring-slate-200" : "hover:bg-white/70")}
              >
                <MessageSquare className="mt-0.5 size-4 shrink-0 text-slate-400" aria-hidden />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm text-slate-800">{c.title}</span>
                  <span className="block text-[0.6875rem] text-slate-400">{formatDate(c.updated_at, true)}</span>
                </span>
              </button>
              <button
                type="button"
                aria-label={`Delete chat ${c.title}`}
                onClick={() => remove(c.id)}
                className="absolute right-1.5 top-2 hidden rounded-md p-1 text-slate-400 hover:bg-red-50 hover:text-red-600 group-hover:block"
              >
                <Trash2 className="size-3.5" />
              </button>
            </li>
          ))}
          {list.data?.length === 0 && <li className="px-3 py-2 text-xs text-slate-400">No chats yet.</li>}
        </ul>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        {/* Phones: the chat list lives in a sheet. */}
        <div className="flex items-center gap-2 border-b border-slate-100 px-3 py-2 lg:hidden">
          <button type="button" onClick={() => setSheet(true)} className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 px-3 py-1.5 text-sm font-medium text-slate-700">
            <MessageSquare className="size-4" aria-hidden /> Chats{list.data?.length ? ` (${list.data.length})` : ""}
          </button>
          <button type="button" onClick={() => open("new")} className="ml-auto inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white">
            <Plus className="size-4" aria-hidden /> New chat
          </button>
        </div>
        <div className="min-h-0 flex-1">
          <ChatPanel key={cid ?? "new"} conversationId={cid} initialPrompt={prompt ?? undefined} onConversation={(id) => open(id)} />
        </div>
      </div>
      {sheet && (
        <div className="fixed inset-0 z-50 flex flex-col bg-slate-900/40 lg:hidden" onClick={() => setSheet(false)}>
          <div className="mt-auto max-h-[75dvh] overflow-y-auto rounded-t-2xl bg-white p-3 pb-[max(0.75rem,env(safe-area-inset-bottom))]" onClick={(e) => e.stopPropagation()}>
            <div className="mb-2 flex items-center justify-between px-1">
              <p className="font-semibold text-slate-900">Your chats</p>
              <button type="button" onClick={() => setSheet(false)} className="rounded-lg px-2 py-1 text-sm text-slate-500">
                Close
              </button>
            </div>
            <ul className="divide-y divide-slate-100">
              {(list.data ?? []).map((c) => (
                <li key={c.id} className="flex items-center gap-2 py-2">
                  <button type="button" onClick={() => { open(c.id); setSheet(false); }} className="min-w-0 flex-1 text-left">
                    <span className={cx("block truncate text-sm", c.id === cid ? "font-semibold text-indigo-700" : "text-slate-800")}>{c.title}</span>
                    <span className="block text-xs text-slate-400">{formatDate(c.updated_at, true)}</span>
                  </button>
                  <button type="button" aria-label={`Delete chat ${c.title}`} onClick={() => remove(c.id)} className="rounded-lg p-2 text-slate-400 hover:bg-red-50 hover:text-red-600">
                    <Trash2 className="size-4" />
                  </button>
                </li>
              ))}
              {list.data?.length === 0 && <li className="py-3 text-sm text-slate-500">No chats yet.</li>}
            </ul>
          </div>
        </div>
      )}
    </div>
  );
}

// Instead of a blank page when something breaks in the browser: a clear message, a way out, and a
// short report to the server so the problem can be found (no personal data, just the error).
import { Component, type ErrorInfo, type ReactNode } from "react";

function report(error: unknown, where: string) {
  try {
    const e = error instanceof Error ? error : new Error(String(error));
    const body = JSON.stringify({ message: e.message.slice(0, 500), stack: (e.stack ?? "").slice(0, 2000), where: where.slice(0, 200),
      path: location.pathname.slice(0, 200), agent: navigator.userAgent.slice(0, 300) });
    void fetch("/api/client-errors", { method: "POST", headers: { "Content-Type": "application/json" }, body, keepalive: true });
  } catch {
    /* reporting must never break the page */
  }
}

let installed = false;
/** Also report errors outside React rendering (event handlers, promises). */
export function installErrorReporting() {
  if (installed) return;
  installed = true;
  window.addEventListener("error", (ev) => report(ev.error ?? ev.message, "window.error"));
  window.addEventListener("unhandledrejection", (ev) => report(ev.reason, "unhandledrejection"));
}

export class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    report(error, (info.componentStack ?? "").split("\n").filter(Boolean)[0]?.trim() ?? "render");
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="mx-auto mt-16 max-w-md rounded-2xl border border-slate-200 bg-white p-6 text-center shadow-soft">
        <p className="text-lg font-semibold text-slate-900">Something went wrong on this page</p>
        <p className="mt-1 text-sm text-slate-600">It has been reported. Reloading usually fixes it.</p>
        <p className="mt-3 break-words rounded-lg bg-slate-50 p-2 text-xs text-slate-500">{this.state.error.message}</p>
        <div className="mt-4 flex justify-center gap-2">
          <button type="button" onClick={() => location.reload()} className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white">
            Reload
          </button>
          <a href="/" className="rounded-lg border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700">
            Go to Dashboard
          </a>
        </div>
      </div>
    );
  }
}

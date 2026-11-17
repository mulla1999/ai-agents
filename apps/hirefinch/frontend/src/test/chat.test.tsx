import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeAll, describe, expect, it } from "vitest";
import { ChatPanel } from "../components/chat/ChatPanel";
import type { ChatMessage } from "../components/chat/types";
import { mockFetch, renderWithProviders } from "./utils";

beforeAll(() => {
  // Newer Chrome returns a Promise here; returning one keeps effects honest (see ChatPanel).
  Element.prototype.scrollIntoView = (() => Promise.resolve()) as unknown as Element["scrollIntoView"];
});

const STATUS = { ai: false, ai_provider: null, ai_error: null, web_search: false, max_chars: 2000 };
const msg = (m: Partial<ChatMessage>): ChatMessage => ({ id: 1, role: "assistant", content: "", created_at: "2026-10-27T10:00:00Z", cards: [], suggestions: [], action: null, ...m });

describe("ChatPanel", () => {
  it("sends a message, shows job cards and confirms an action only on click", async () => {
    const calls = mockFetch(({ method, path, body }) => {
      if (path === "/assistant/status") return { json: STATUS };
      if (method === "GET" && path === "/assistant/conversations/7") return { json: { id: 7, title: "x", created_at: "", updated_at: "", messages: [] } };
      if (method === "POST" && path === "/assistant/conversations/7/messages") {
        const text = (body as { text: string }).text;
        if (text.startsWith("Apply"))
          return {
            json: {
              messages: [
                msg({ id: 3, role: "user", content: text }),
                msg({ id: 4, content: "Ready to apply.", action: { id: 9, kind: "apply", summary: "Submit your application for Backend Engineer at Acme", status: "pending", result: null } }),
              ],
            },
          };
        return {
          json: {
            messages: [
              msg({ id: 1, role: "user", content: text }),
              msg({
                id: 2,
                content: "Jobs found:\n- #12 Backend Engineer",
                cards: [{ type: "jobs", items: [{ id: 12, title: "Backend Engineer", company: "Acme", location: "Pune", work_mode: "hybrid", url: "https://x", status: "match_evaluated", posted_at: null, salary: null, score: 88, band: "high", apply_method: "email", suspicious: false }] }],
              }),
            ],
          },
        };
      }
      if (method === "POST" && path === "/assistant/actions/9/confirm")
        return { json: { action: { id: 9, kind: "apply", summary: "Submit…", status: "done", result: "Submitted." }, messages: [msg({ id: 5, content: "Submitted your application." })] } };
    });
    const user = userEvent.setup();
    renderWithProviders(<ChatPanel conversationId={7} />);

    await user.type(await screen.findByLabelText("Message"), "find backend jobs{Enter}");
    expect(await screen.findByRole("link", { name: "Backend Engineer" })).toHaveAttribute("href", "/jobs/12");
    expect(screen.getByText("88")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Apply" }));
    expect(await screen.findByText(/Submit your application for Backend Engineer/)).toBeInTheDocument();
    expect(calls.some((c) => c.path.endsWith("/confirm"))).toBe(false); // nothing runs without a click

    await user.click(screen.getByRole("button", { name: /confirm/i }));
    expect(await screen.findByText("Submitted your application.")).toBeInTheDocument();
    await waitFor(() => expect(calls.filter((c) => c.path === "/assistant/actions/9/confirm")).toHaveLength(1));
  });

  it("renders untrusted text as text, never as HTML", async () => {
    mockFetch(({ path }) => {
      if (path === "/assistant/status") return { json: STATUS };
      if (path === "/assistant/conversations/8")
        return { json: { id: 8, title: "x", created_at: "", updated_at: "", messages: [msg({ content: '<img src=x onerror="alert(1)"> hello' })] } };
    });
    const { container } = renderWithProviders(<ChatPanel conversationId={8} />);
    expect(await screen.findByText(/hello/)).toBeInTheDocument();
    expect(container.querySelector("img")).toBeNull();
  });
});

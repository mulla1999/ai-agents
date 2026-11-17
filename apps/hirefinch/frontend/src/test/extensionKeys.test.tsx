import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { EXTENSION_ID, ExtensionKeys } from "../components/ExtensionKeys";
import { mockFetch, renderWithProviders } from "./utils";

const KEYS = () => ({ json: [] });

function fakeExtension(connected: boolean) {
  const sent: { id: string; msg: { type: string; token?: string } }[] = [];
  vi.stubGlobal("chrome", {
    runtime: {
      sendMessage: (id: string, msg: { type: string; token?: string }, reply: (r: unknown) => void) => {
        sent.push({ id, msg });
        reply(msg.type === "ping" ? { installed: true, version: "1.3.0", connected } : { opened: true });
      },
    },
  });
  return sent;
}

describe("ExtensionKeys", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("shows not installed and keeps Connect disabled until the extension is there", async () => {
    mockFetch((c) => (c.path === "/account/extension-tokens" ? KEYS() : undefined));
    renderWithProviders(<ExtensionKeys />);
    expect(await screen.findByText("not installed")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Connect extension/ })).toBeDisabled();
  });

  it("creates a key and hands it to the installed extension in one click", async () => {
    const sent = fakeExtension(false);
    const calls = mockFetch((c) =>
      c.path === "/account/extension-tokens" ? (c.method === "POST" ? { json: { id: 1, token: "jae_abcdefghijklmnopqrstuvwxyz" } } : KEYS()) : undefined,
    );
    renderWithProviders(<ExtensionKeys />);
    expect(await screen.findByText("installed, not connected yet")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Connect extension/ }));
    await waitFor(() => expect(sent.some((s) => s.msg.type === "connect")).toBe(true));
    const offer = sent.find((s) => s.msg.type === "connect")!;
    expect(offer.id).toBe(EXTENSION_ID);
    expect(offer.msg.token).toBe("jae_abcdefghijklmnopqrstuvwxyz");
    expect(calls.some((c) => c.method === "POST")).toBe(true);
    expect(await screen.findByText(/opened its settings tab/)).toBeInTheDocument();
  });

  it("says it is connected", async () => {
    fakeExtension(true);
    mockFetch((c) => (c.path === "/account/extension-tokens" ? KEYS() : undefined));
    renderWithProviders(<ExtensionKeys />);
    expect(await screen.findByText(/connected · v1.3.0/)).toBeInTheDocument();
  });

  it("explains that phones can't run extensions", async () => {
    vi.spyOn(navigator, "userAgent", "get").mockReturnValue("Mozilla/5.0 (Linux; Android 10; K) Chrome/156.0 Mobile Safari/537.36");
    mockFetch((c) => (c.path === "/account/extension-tokens" ? KEYS() : undefined));
    renderWithProviders(<ExtensionKeys />);
    expect(screen.getByText(/Phone browsers can't run extensions/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Connect extension/ })).not.toBeInTheDocument();
  });
});

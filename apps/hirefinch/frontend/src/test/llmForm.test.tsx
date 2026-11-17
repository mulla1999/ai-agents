import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { LlmForm, type ConnectionActions } from "../components/ConnectionForms";
import { mockFetch, renderWithProviders } from "./utils";

const actions: ConnectionActions = { save: () => undefined, saving: false, saveError: null };
const empty = { kind: "llm", configured: false, config: {}, secrets_set: [] };

describe("AI provider form", () => {
  it("offers a free Gemini key and fills the model list with the recommended model selected", async () => {
    const calls = mockFetch(({ path }) => {
      if (path === "/integrations/llm/models")
        return { json: { recommended: "gemini-3.5-flash", models: [
          { id: "gemini-3.5-flash", label: "gemini-3.5-flash · recommended", recommended: true },
          { id: "gemini-3.8-flash", label: "gemini-3.8-flash", recommended: false }] } };
    });
    const user = userEvent.setup();
    renderWithProviders(<LlmForm view={empty} actions={actions} />);

    const link = screen.getByRole("link", { name: /get a free gemini key/i });
    expect(link).toHaveAttribute("href", "https://aistudio.google.com/apikey");
    expect(link).toHaveAttribute("target", "_blank");

    await user.type(screen.getByLabelText("API key"), "AIza-test-key");
    await waitFor(() => expect(calls.some((c) => c.path === "/integrations/llm/models")).toBe(true), { timeout: 3000 });
    const select = (await screen.findByDisplayValue("gemini-3.5-flash · recommended")) as HTMLSelectElement;
    expect(select.value).toBe("gemini-3.5-flash");
    expect(calls.find((c) => c.path === "/integrations/llm/models")!.body).toMatchObject({ provider: "gemini", api_key: "AIza-test-key" });
  });

  it("switches to Groq with the base URL filled in", async () => {
    mockFetch(() => undefined);
    const user = userEvent.setup();
    renderWithProviders(<LlmForm view={empty} actions={actions} />);
    await user.click(screen.getByRole("button", { name: /use groq instead/i }));
    expect(screen.getByDisplayValue("https://api.groq.com/openai/v1")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /get a free groq key/i })).toHaveAttribute("href", "https://console.groq.com/keys");
  });
});

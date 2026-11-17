import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { Integrations } from "../api/types";
import { IntegrationsPage } from "../pages/Integrations";
import { mockFetch, renderWithProviders } from "./utils";

const view = (kind: string, secrets: string[] = []) => ({ kind, configured: secrets.length > 0, config: {}, secrets_set: secrets });

const DATA: Integrations = {
  integrations: { email: view("email"), llm: view("llm"), jooble: view("jooble", ["api_key"]) },
  sources: [],
  notification_email_set: true,
  unsupported: [],
};

describe("IntegrationsPage", () => {
  it("never pre-fills a saved secret and sends a blank one as empty", async () => {
    const calls = mockFetch(({ method, path }) => {
      if (method === "GET" && path === "/integrations") return { json: DATA };
      if (method === "PUT" && path === "/integrations/jooble") return { json: view("jooble", ["api_key"]) };
    });
    const user = userEvent.setup();
    renderWithProviders(<IntegrationsPage />);

    const heading = await screen.findByRole("heading", { name: /jooble job search/i });
    await user.click(within(heading).getByRole("button")); // sections start closed
    const card = heading.closest("section")!;
    const secret = within(card).getByLabelText("API key") as HTMLInputElement;
    expect(secret.value).toBe("");
    expect(secret.type).toBe("password");
    expect(secret).toHaveAttribute("placeholder", expect.stringMatching(/saved/));

    await user.click(within(card).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
    const put = calls.find((c) => c.method === "PUT")!;
    expect(put.path).toBe("/integrations/jooble");
    expect(put.body).toEqual({ config: {}, secrets: { api_key: "" } });
  });

  it("finds a company's job board and follows it", async () => {
    const calls = mockFetch(({ method, path }) => {
      if (method === "GET" && path === "/integrations") return { json: DATA };
      if (method === "GET" && path.startsWith("/sources/find-company?q=Acme")) {
        return { json: { results: [{ kind: "greenhouse", token: "acme", company: "Acme", jobs: 12, india_jobs: 4, added: false }] } };
      }
      if (method === "POST" && path === "/sources/greenhouse/boards") return { json: [] };
    });
    const user = userEvent.setup();
    renderWithProviders(<IntegrationsPage />);

    await user.type(await screen.findByLabelText("Company name or careers link"), "Acme");
    await user.click(screen.getByRole("button", { name: /find/i }));
    expect(await screen.findByText(/Greenhouse · 12 open jobs · 4 in India/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Add" }));
    expect(await screen.findByText("following")).toBeInTheDocument();
    expect(calls.find((c) => c.method === "POST")!.body).toEqual({ token: "acme", company: "Acme" });
  });
});

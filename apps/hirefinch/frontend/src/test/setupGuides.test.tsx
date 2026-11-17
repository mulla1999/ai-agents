import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { EmailForm, ImapForm, WebSearchForm, type ConnectionActions } from "../components/ConnectionForms";
import { renderWithProviders } from "./utils";

const actions: ConnectionActions = { save: () => undefined, saving: false, saveError: null };
const view = (kind: string, configured = false) => ({ kind, configured, config: {}, secrets_set: [] });

describe("integration setup guides", () => {
  it("guides Gmail setup and fills the SMTP settings", async () => {
    const user = userEvent.setup();
    renderWithProviders(<EmailForm title="Your email" description="" view={view("email")} actions={actions} />);
    const guide = screen.getByText(/How to set this up with Gmail/).closest("details")!;
    expect(guide.open).toBe(true);
    expect(screen.getByRole("link", { name: /create an app password/i })).toHaveAttribute("href", "https://myaccount.google.com/apppasswords");
    await user.click(screen.getByRole("button", { name: /fill in gmail settings/i }));
    expect(screen.getByDisplayValue("smtp.gmail.com")).toBeInTheDocument();
    expect(screen.getByDisplayValue("587")).toBeInTheDocument();
  });

  it("is collapsed once the connection is set up", () => {
    renderWithProviders(<EmailForm title="Your email" description="" view={view("email", true)} actions={actions} />);
    expect(screen.getByText(/How to set this up with Gmail/).closest("details")!.open).toBe(false);
  });

  it("links to the job-alert sites and recommends a no-card web-search key", () => {
    renderWithProviders(<><ImapForm view={view("imap")} actions={actions} /><WebSearchForm view={view("websearch")} actions={actions} /></>);
    expect(screen.getByRole("link", { name: /linkedin job alerts/i })).toHaveAttribute("target", "_blank");
    expect(screen.getByRole("link", { name: /naukri job alerts/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /get a free tavily key/i })).toHaveAttribute("href", "https://app.tavily.com/");
    expect(screen.getByDisplayValue("Tavily (free, no card)")).toBeInTheDocument();
  });
});

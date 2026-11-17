import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";
import { ResumeBuilderPage } from "../pages/ResumeBuilder";
import { mockFetch, renderWithProviders } from "./utils";

describe("ResumeBuilderPage", () => {
  afterEach(() => localStorage.clear());

  it("asks for a real number instead of inventing one, then uses the person's answer", async () => {
    const calls = mockFetch(({ method, path, body }) => {
      if (path === "/resumes/masters") return { json: [] };
      if (path === "/assistant/status") return { json: { ai: true } };
      if (path === "/resume-builder/review") return { json: { score: 70, tips: [] } };
      if (method === "POST" && path === "/resume-builder/improve-bullet") {
        const facts = (body as { facts: string }).facts;
        return facts
          ? { json: { text: "Built the login API, cutting sign-in time 40%", question: "", rejected: "" } }
          : { json: { text: "", question: "How much faster did sign-in get?", rejected: "The suggestion was not used: it numbers added or dropped." } };
      }
    });
    const user = userEvent.setup();
    renderWithProviders(<ResumeBuilderPage />);

    await user.click(await screen.findByRole("button", { name: /Start blank/ }));
    await user.type(screen.getByLabelText("Bullet"), "made login api");
    await user.click(screen.getByRole("button", { name: /Improve/ }));

    const answer = await screen.findByPlaceholderText(/Your real answer/);
    expect(screen.getByText(/never adds facts you didn't write/)).toBeInTheDocument();
    await user.type(answer, "sign-in got 40% faster");
    await user.click(screen.getByRole("button", { name: "Rewrite with my answer" }));
    await user.click(await screen.findByRole("button", { name: "Use this" }));

    expect(screen.getByLabelText("Bullet")).toHaveValue("Built the login API, cutting sign-in time 40%");
    const sent = calls.filter((c) => c.path === "/resume-builder/improve-bullet").map((c) => (c.body as { facts: string }).facts);
    expect(sent).toEqual(["", "sign-in got 40% faster"]);
    // The draft is kept in this browser.
    await waitFor(() => expect(localStorage.getItem("hirefinch:resume-builder")).toContain("cutting sign-in time 40%"));
  });

  it("fixes all it can, shows the changes, and applies them only on request", async () => {
    mockFetch(({ method, path, body }) => {
      if (path === "/resumes/masters") return { json: [] };
      if (path === "/assistant/status") return { json: { ai: true } };
      if (path === "/resume-builder/review") return { json: { score: 60, tips: [{ level: "fix", section: "bullets", message: "Duty language", target: null }] } };
      if (method === "POST" && path === "/resume-builder/fix-all") {
        const doc = body as { experience: { bullets: { id: string; text: string }[] }[] };
        const fixed = structuredClone(doc);
        fixed.experience[0].bullets[0].text = "Built the login API";
        return { json: { document: fixed, changes: [{ op: "bullet", section: "bullet", id: fixed.experience[0].bullets[0].id, before: "made login api", after: "Built the login API" }],
          score_before: 60, score_after: 92, remaining: [{ level: "improve", section: "contact", message: "Add your LinkedIn profile link.", target: null }], note: "" } };
      }
    });
    const user = userEvent.setup();
    renderWithProviders(<ResumeBuilderPage />);
    await user.click(await screen.findByRole("button", { name: /Start blank/ }));
    await user.type(screen.getByLabelText("Bullet"), "made login api");
    await user.click(await screen.findByRole("button", { name: /Fix all I can/ }));
    expect(await screen.findByText(/Score 60/)).toBeInTheDocument();
    expect(screen.getByText("Add your LinkedIn profile link.")).toBeInTheDocument();
    expect(screen.getByLabelText("Bullet")).toHaveValue("made login api"); // nothing changed yet
    await user.click(screen.getByRole("button", { name: /Apply 1 fix/ }));
    expect(screen.getByLabelText("Bullet")).toHaveValue("Built the login API");
  });

  it("runs the ATS read-back test and offers missing job keywords", async () => {
    mockFetch(({ method, path }) => {
      if (path === "/resumes/masters") return { json: [] };
      if (path === "/assistant/status") return { json: { ai: false } };
      if (path === "/resume-builder/review") return { json: { score: 90, tips: [] } };
      if (path.startsWith("/jobs?")) return { json: { items: [{ id: 5, title: "Backend Engineer", company: "Acme" }] } };
      if (method === "POST" && path === "/resume-builder/ats-test")
        return {
          json: {
            readability: { score: 100, pages: 1, checks: [{ check: "ATS: no header or footer", ok: true, detail: "", severity: "error" }],
              files: { PDF: { read: 34, total: 34, misses: [] }, Word: { read: 34, total: 34, misses: [] } } },
            keywords: { required_found: ["Java"], required_missing: ["Kotlin"], preferred_found: [], preferred_missing: [] },
          },
        };
    });
    const user = userEvent.setup();
    renderWithProviders(<ResumeBuilderPage />);
    await user.click(await screen.findByRole("button", { name: /Start blank/ }));
    expect(await screen.findByText("PDF: 34 of 34 facts read back", undefined, { timeout: 5000 })).toBeInTheDocument();
    expect(screen.getByText("100%")).toBeInTheDocument();
    expect(screen.getByText("Required: 1 of 2 found")).toBeInTheDocument();
    expect(screen.getByText("Ready to send")).toBeInTheDocument();
    expect(screen.getByText("An ATS can read every fact in it.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Kotlin/ })).toBeInTheDocument();
  }, 10000);

  it("starts from any uploaded resume and notices when the resume in use changes", async () => {
    const active: number = 2; // the newer upload is in use
    const masters = () => [
      { id: 1, filename: "Old_Resume.pdf", is_active: active === 1, uploaded_at: "2026-10-06T10:00:00Z", experience_count: 2, skills_count: 10 },
      { id: 2, filename: "New_Resume.pdf", is_active: active === 2, uploaded_at: "2026-11-01T10:00:00Z", experience_count: 3, skills_count: 60 },
    ];
    mockFetch(({ path }) => {
      if (path === "/resumes/masters") return { json: masters() };
      if (path === "/resumes/masters/1") return { json: { document: { contact: { name: "Old Me", headline: null, email: null, phone: null, location: null, links: [] }, summary: "", skills: [], experience: [], projects: [], education: [], certifications: [], extra_sections: [], warnings: [] } } };
      if (path === "/assistant/status") return { json: { ai: false } };
      if (path === "/resume-builder/review") return { json: { score: 50, tips: [] } };
    });
    const user = userEvent.setup();
    renderWithProviders(<ResumeBuilderPage />);
    expect(await screen.findByText("New_Resume.pdf")).toBeInTheDocument(); // every upload is offered
    const useButtons = screen.getAllByRole("button", { name: /Use this/ });
    await user.click(useButtons[1]); // the second row is Old_Resume.pdf: the one in use is listed first
    expect(await screen.findByText(/Draft from/)).toHaveTextContent("Old_Resume.pdf");
    // Working on an older upload: the page points out which resume is in use.
    expect(await screen.findByText(/Your resume in use is now/)).toHaveTextContent("New_Resume.pdf");
  });
});

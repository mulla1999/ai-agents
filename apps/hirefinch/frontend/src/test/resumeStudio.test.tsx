import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router";
import { describe, expect, it } from "vitest";
import { ResumeStudioPage } from "../pages/ResumeStudio";
import { mockFetch } from "./utils";

const job = (title: string, company: string) => ({ title, company, location: "Pune", status: "resume_ready", url: "https://x", score: 92, band: "high" });
const version = (id: number, jobId: number, no: number, j: ReturnType<typeof job>) => ({
  id, job_id: jobId, version_no: no, role_family: "java_backend", template_version: "ats-classic-2", valid: true,
  created_at: `2026-10-2${no}T10:00:00Z`, docx_name: "a.docx", pdf_name: "a.pdf", docx_sha256: "x", pdf_sha256: "y",
  validation: { passed: true, errors: [], warnings: [] }, job: j,
});
const citi = job("Backend Java Developer", "Citi");
const VERSIONS = [version(3, 283, 2, citi), version(2, 283, 1, citi), version(1, 252, 1, job("Software Engineer II", "JPMorganChase"))];

function renderAt(path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/resumes" element={<ResumeStudioPage />} />
          <Route path="/resumes/:versionId" element={<ResumeStudioPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("Resume Studio", () => {
  it("lists one entry per job by title and company, searches, and opens the resume with a way back", async () => {
    mockFetch(({ path }) => {
      if (path === "/resumes/versions") return { json: VERSIONS };
      if (path === "/resumes/versions/3")
        return { json: { ...VERSIONS[0], content: {}, text: "PRIYA SHARMA\\nSoftware Engineer", master_text: "", versions: [
          { id: 3, version_no: 2, valid: true, created_at: VERSIONS[0].created_at }, { id: 2, version_no: 1, valid: true, created_at: VERSIONS[1].created_at }],
          validation: { passed: true, errors: [], warnings: [], checks: [] },
          report: { role_family: "java_backend", changes: ["Skills reordered"], omitted_bullets: [], gaps: [], llm: "not used", diff: "",
            keyword_coverage: { covered: ["Java"], missing_not_in_profile: [], missing_but_verified: [] } } } };
    });
    const user = userEvent.setup();
    renderAt("/resumes");
    expect(await screen.findByRole("button", { name: /Backend Java Developer/ })).toBeInTheDocument();
    expect(screen.getByText("2 versions", { exact: false })).toBeInTheDocument();
    expect(screen.queryByText(/Job #283/)).not.toBeInTheDocument(); // no bare job numbers

    await user.type(screen.getByPlaceholderText("Search by job or company"), "jpmorgan");
    expect(screen.queryByRole("button", { name: /Backend Java Developer/ })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Software Engineer II/ })).toBeInTheDocument();
    await user.clear(screen.getByPlaceholderText("Search by job or company"));

    await user.click(screen.getByRole("button", { name: /Backend Java Developer/ }));
    expect(await screen.findByRole("link", { name: /all resumes/i })).toHaveAttribute("href", "/resumes");
    expect(await screen.findByRole("heading", { name: "Backend Java Developer" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /v1 ·/ })).toHaveAttribute("href", "/resumes/2");
    expect(screen.getByRole("link", { name: /open pdf/i })).toHaveAttribute("href", "/api/resumes/versions/3/download?format=pdf");
  });
});

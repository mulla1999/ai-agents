import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { InterviewPrep, type Prep } from "../components/InterviewPrep";
import { mockFetch, renderWithProviders } from "./utils";

const PREP: Prep = {
  technical: [{ question: "Tell me about a time you used Kafka.", skill: "Kafka", your_points: [{ id: "b1", text: "Built a Kafka pipeline", where: "Engineer at Acme" }] }],
  role: [{ question: "Walk me through your background.", tip: "Two minutes." }],
  gaps: [{ topic: "Kubernetes", how_to_answer: "Be straightforward." }],
  story_starters: [],
  stories: [{ title: "Payments pipeline", situation: "S", task: "T", action: "A", result: "R", sources: ["Built a Kafka pipeline"], good_for: ["ownership"] }],
  questions: [{ question: "How do you handle retries?", type: "technical", why: "event-driven work" }],
  ask: ["How is on-call shared?"],
  note: null,
  used_llm: true,
  created_at: "2026-11-02T10:00:00Z",
};

describe("InterviewPrep", () => {
  it("prepares on request and shows stories, questions, gaps and what to ask", async () => {
    let made = false;
    mockFetch(({ method, path }) => {
      if (path === "/jobs/7/interview-prep" && method === "GET") return { json: { prep: made ? PREP : null } };
      if (path === "/jobs/7/interview-prep" && method === "POST") {
        made = true;
        return { json: { prep: PREP } };
      }
    });
    const user = userEvent.setup();
    renderWithProviders(<InterviewPrep jobId={7} interviewing />);
    await user.click(await screen.findByRole("button", { name: /Prepare me/ }));
    expect(await screen.findByText("Payments pipeline")).toBeInTheDocument();
    expect(screen.getByText("How do you handle retries?")).toBeInTheDocument();
    expect(screen.getAllByText(/Built a Kafka pipeline/).length).toBe(2); // the skill point and the story source
    expect(screen.getByText("Kubernetes")).toBeInTheDocument();
    expect(screen.getByText("How is on-call shared?")).toBeInTheDocument();
  });
});

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { TopSkillGaps } from "../components/SkillGaps";
import { mockFetch, renderWithProviders } from "./utils";

describe("Skill gaps", () => {
  it("asks where you used a skill, then reports how many jobs were re-scored", async () => {
    const calls = mockFetch(({ method, path, body }) => {
      if (path === "/skills/gaps") return { json: [{ skill: "OOP", jobs: 9 }, { skill: "Kotlin", jobs: 12 }] };
      if (method === "POST" && path === "/skills/answer") {
        const b = body as { skill: string; knows: boolean };
        return { json: { skill: b.skill, knows: b.knows, rescored: b.knows ? 9 : 0 } };
      }
    });
    const user = userEvent.setup();
    renderWithProviders(<TopSkillGaps />);

    expect(await screen.findByText("9 jobs")).toBeInTheDocument();
    const [knowOop] = screen.getAllByRole("button", { name: "I know this" });
    await user.click(knowOop);
    const save = screen.getByRole("button", { name: "Save" });
    expect(save).toBeDisabled(); // a word on where is required
    await user.type(screen.getByPlaceholderText(/Where have you used OOP/), "Java services built with SOLID principles");
    await user.click(save);
    expect(await screen.findByText(/9 jobs re-scored/)).toBeInTheDocument();

    // OOP is answered, so only Kotlin's buttons are left.
    await user.click(screen.getByRole("button", { name: "No" }));
    expect(await screen.findByText(/You won't be asked again/)).toBeInTheDocument();
    const answers = calls.filter((c) => c.path === "/skills/answer").map((c) => c.body);
    expect(answers).toEqual([
      { skill: "OOP", knows: true, evidence: "Java services built with SOLID principles" },
      { skill: "Kotlin", knows: false, evidence: "" },
    ]);
  });
});

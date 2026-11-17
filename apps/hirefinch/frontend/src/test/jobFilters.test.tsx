import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it } from "vitest";
import { FILTER_KEYS, JobFilters, type FilterValues } from "../components/JobFilters";
import { renderWithProviders } from "./utils";

const empty = Object.fromEntries(FILTER_KEYS.map((k) => [k, ""])) as FilterValues;

function Harness({ log }: { log: Partial<FilterValues>[] }) {
  const [values, setValues] = useState(empty);
  return (
    <JobFilters
      values={values}
      total={42}
      sources={[]}
      onChange={(patch) => {
        log.push(patch);
        setValues((v) => ({ ...v, ...patch }));
      }}
      onClear={() => setValues(empty)}
    />
  );
}

describe("JobFilters", () => {
  it("toggles quick filters, applies the panel only on Show results, and removes chips", async () => {
    const log: Partial<FilterValues>[] = [];
    const user = userEvent.setup();
    renderWithProviders(<Harness log={log} />);
    expect(screen.getByText("42 jobs")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Remote" }));
    expect(screen.getByRole("button", { name: "Remote" })).toHaveAttribute("aria-pressed", "true");

    await user.click(screen.getByRole("button", { name: /filters/i }));
    await user.type(screen.getByPlaceholderText("e.g. Pune"), "Pune");
    await user.click(screen.getByRole("checkbox", { name: "Shortlisted" }));
    expect(log.some((p) => p.location)).toBe(false); // draft until applied
    await user.click(screen.getByRole("button", { name: "Show results" }));
    expect(screen.getByText("Location: Pune")).toBeInTheDocument();
    expect(screen.getByText("Shortlisted", { selector: "span span" })).toBeInTheDocument();

    await user.click(within(screen.getByText("Location: Pune").parentElement!).getByRole("button", { name: "Remove filter" }));
    await waitFor(() => expect(screen.queryByText("Location: Pune")).not.toBeInTheDocument());
  });

  it("blocks impossible ranges before searching", async () => {
    const user = userEvent.setup();
    renderWithProviders(<Harness log={[]} />);
    await user.click(screen.getByRole("button", { name: /filters/i }));
    await user.type(screen.getByLabelText("Minimum score"), "90");
    await user.type(screen.getByLabelText("Maximum score"), "50");
    expect(screen.getByRole("alert")).toHaveTextContent("above the maximum");
    expect(screen.getByRole("button", { name: "Show results" })).toBeDisabled();
  });
});

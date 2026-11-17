import { describe, expect, it } from "vitest";
import { ctcProblem } from "../pages/Profile";

describe("CTC validation (lakhs per annum)", () => {
  it("flags rupee amounts and shows the conversion", () => {
    expect(ctcProblem(1249000)).toMatch(/₹12,49,000 is 12\.49 LPA/);
    expect(ctcProblem(2000000)).toMatch(/20 LPA/);
    expect(ctcProblem(0)).toMatch(/above 0/);
  });

  it("accepts real LPA values and empty", () => {
    for (const v of [12.49, 20, 500, null]) expect(ctcProblem(v)).toBeNull();
  });
});

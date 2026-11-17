import { describe, expect, it } from "vitest";
import type { AuditEvent } from "../api/types";
import { describeEvent, isHousekeeping } from "../pages/Audit";

const ev = (action: string, message: string, extra: Partial<AuditEvent> = {}): AuditEvent => ({
  id: 1, at: "2026-11-01T10:00:00Z", actor: "agent", action, level: "info", entity_type: null, entity_id: null, message, details: {}, ...extra,
});

describe("describeEvent", () => {
  it("turns a status change into words and links the job", () => {
    const r = describeEvent(ev("job.status", "resume_ready → awaiting_approval: needs approval", {
      entity_type: "job", entity_id: 284, details: { from: "resume_ready", to: "awaiting_approval" },
    }));
    expect(r.text).toBe("A job moved to “Ready for you” (needs approval)");
    expect(r.to).toBe("/jobs/284");
  });

  it("explains failures and search results without ids", () => {
    expect(describeEvent(ev("outreach.failed", "outreach 4 failed: attachment Priya_Sharma_Resume.pdf is missing")).text)
      .toBe("A recruiter email couldn't be sent: attachment Priya_Sharma_Resume.pdf is missing");
    expect(describeEvent(ev("source.run", "The Muse: 5 new, 0 updated, 1 duplicates")).text).toBe("The Muse searched: 5 new jobs");
    expect(describeEvent(ev("source.run", "The Muse: 0 new, 0 updated")).text).toBe("The Muse searched: no new jobs");
    expect(describeEvent(ev("integration.saved", "llm settings saved")).text).toBe("AI provider settings saved");
  });

  it("humanises unknown actions and keeps housekeeping off the dashboard", () => {
    expect(describeEvent(ev("jobs.something_new", "")).text).toBe("Jobs something new");
    expect(isHousekeeping(ev("platform.settings", "platform setting 'registration' updated"))).toBe(true);
    expect(isHousekeeping(ev("account.login", "signed in"))).toBe(true);
    expect(isHousekeeping(ev("job.status", "x"))).toBe(false);
  });
});

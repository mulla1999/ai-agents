// Skills a job asks for that your resume doesn't show. Answer once per skill: "I know this" (with a line
// on where you used it) adds it to your skills and re-scores every job that asked for it; "No" is
// remembered so you're not asked again.

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Check } from "lucide-react";
import { useState } from "react";
import { api } from "../api/client";
import { Badge, Button, Card, ErrorText, useAction } from "./ui";

export interface SkillGap {
  skill: string;
  required: boolean;
  declined: boolean;
}

interface AnswerResult {
  skill: string;
  knows: boolean;
  rescored: number;
}

export function useJobSkillGaps(jobId: number) {
  return useQuery({ queryKey: ["skill-gaps", jobId], queryFn: () => api<SkillGap[]>(`/jobs/${jobId}/skill-gaps`) });
}

export function SkillAnswer({ skill, label }: { skill: string; label?: React.ReactNode }) {
  const client = useQueryClient();
  const [asking, setAsking] = useState(false);
  const [evidence, setEvidence] = useState("");
  const [done, setDone] = useState<AnswerResult | null>(null);
  const answer = useAction(
    (knows: boolean) => api<AnswerResult>("/skills/answer", { method: "POST", body: { skill, knows, evidence } }),
    (r) => {
      setDone(r);
      // Scores, gaps and the job lists all change after an answer.
      for (const key of ["skill-gaps", "top-skill-gaps", "job", "jobs", "dashboard", "profile"]) void client.invalidateQueries({ queryKey: [key] });
    },
  );
  if (done) {
    return (
      <li className="flex items-center gap-2 py-2 text-sm text-slate-600">
        <Check className="size-4 text-emerald-600" aria-hidden />
        {done.knows ? (
          <span>
            <b className="text-slate-900">{done.skill}</b> added to your skills
            {done.rescored ? ` · ${done.rescored} job${done.rescored === 1 ? "" : "s"} re-scored` : ""}.
          </span>
        ) : (
          <span>
            Got it: you don't have <b className="text-slate-900">{done.skill}</b>. You won't be asked again.
          </span>
        )}
      </li>
    );
  }
  return (
    <li className="py-2">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium text-slate-900">{skill}</span>
        {label}
        {!asking && (
          <span className="ml-auto flex gap-1.5">
            <Button className="py-1" onClick={() => setAsking(true)}>
              I know this
            </Button>
            <Button variant="ghost" className="py-1" busy={answer.isPending && answer.variables === false} onClick={() => answer.mutate(false)}>
              No
            </Button>
          </span>
        )}
      </div>
      {asking && (
        <form
          className="mt-2 flex flex-col gap-2 sm:flex-row"
          onSubmit={(e) => {
            e.preventDefault();
            answer.mutate(true);
          }}
        >
          <input
            autoFocus
            value={evidence}
            maxLength={300}
            onChange={(e) => setEvidence(e.target.value)}
            placeholder={`Where have you used ${skill}? e.g. Java services at your current job`}
            className="min-w-0 flex-1 rounded-lg border border-slate-200 px-3 py-2 text-sm focus:border-indigo-400 focus:outline-none focus:ring-2 focus:ring-indigo-100"
          />
          <div className="flex gap-1.5">
            <Button type="submit" variant="primary" disabled={evidence.trim().length < 3} busy={answer.isPending && answer.variables === true}>
              Save
            </Button>
            <Button variant="ghost" onClick={() => setAsking(false)}>
              Cancel
            </Button>
          </div>
        </form>
      )}
      <ErrorText error={answer.error} />
    </li>
  );
}

/** On a job page: the job's missing skills you haven't answered about. */
export function JobSkillGaps({ jobId }: { jobId: number }) {
  const gaps = useJobSkillGaps(jobId);
  const open = (gaps.data ?? []).filter((g) => !g.declined);
  const declined = (gaps.data ?? []).filter((g) => g.declined);
  if (!gaps.data?.length) return null;
  return (
    <div>
      {open.length > 0 && (
        <>
          <p className="mb-1 text-xs text-slate-500">Your resume doesn't show these. If you know one, say where you used it: your score updates right away.</p>
          <ul className="divide-y divide-slate-100">
            {open.map((g) => (
              <SkillAnswer key={g.skill} skill={g.skill} label={<Badge tone={g.required ? "red" : "slate"}>{g.required ? "required" : "nice to have"}</Badge>} />
            ))}
          </ul>
        </>
      )}
      {declined.length > 0 && <p className="mt-1 text-xs text-slate-500">You said you don't have: {declined.map((g) => g.skill).join(", ")}.</p>}
    </div>
  );
}

/** Dashboard: the skills your open jobs most often say you're missing. One answer re-scores them all. */
export function TopSkillGaps() {
  const gaps = useQuery({ queryKey: ["top-skill-gaps"], queryFn: () => api<{ skill: string; jobs: number }[]>("/skills/gaps") });
  if (!gaps.data?.length) return null;
  return (
    <Card title="Skills your jobs keep asking for">
      <p className="mb-1 text-sm text-slate-600">Your resume doesn't show these. If you know one, answer once and every job that asks for it is re-scored.</p>
      <ul className="divide-y divide-slate-100">
        {gaps.data.map((g) => (
          <SkillAnswer key={g.skill} skill={g.skill} label={<span className="text-xs text-slate-500">{g.jobs} job{g.jobs === 1 ? "" : "s"}</span>} />
        ))}
      </ul>
    </Card>
  );
}

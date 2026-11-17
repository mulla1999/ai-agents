// Interview prep for one job: likely questions with the parts of your resume that answer them, your STAR
// stories (built only from your own bullets), how to handle gaps, and questions to ask the interviewer.

import { useQuery } from "@tanstack/react-query";
import { Sparkles } from "lucide-react";
import { api } from "../api/client";
import { Alert, Badge, Button, Card, Collapsible, ErrorText, Loading, formatDate, useAction } from "./ui";

interface Point {
  id: string;
  text: string;
  where: string;
}
interface Story {
  title: string;
  situation: string;
  task: string;
  action: string;
  result: string;
  sources: string[];
  good_for: string[];
}
export interface Prep {
  technical: { question: string; skill: string; your_points: Point[] }[];
  role: { question: string; tip: string }[];
  gaps: { topic: string; how_to_answer: string }[];
  story_starters: { bullet: Point; prompts: string[] }[];
  questions?: { question: string; type: string; why: string }[];
  stories?: Story[];
  ask: string[];
  note: string | null;
  used_llm: boolean;
  created_at: string;
}

export function InterviewPrep({ jobId, interviewing }: { jobId: number; interviewing: boolean }) {
  const query = useQuery({ queryKey: ["interview-prep", jobId], queryFn: () => api<{ prep: Prep | null }>(`/jobs/${jobId}/interview-prep`) });
  const make = useAction(() => api<{ prep: Prep }>(`/jobs/${jobId}/interview-prep`, { method: "POST" }));
  const prep = query.data?.prep;
  return (
    <Collapsible
      defaultOpen={interviewing}
      summary={prep ? `Ready · prepared ${formatDate(prep.created_at)}` : interviewing ? "Your interview is coming up: get ready here" : "Likely questions, your stories and what to ask"}
    >
      <Card title="Interview prep">
        <div id="interview" className="space-y-5 text-sm">
          {query.isLoading ? (
            <Loading />
          ) : !prep ? (
            <div>
              <p className="mb-3 text-slate-600">
                HireFinch prepares likely questions for this job, shows which parts of your resume answer them, and turns your bullets into short stories
                you can tell. Everything comes from your own resume.
              </p>
              <Button variant="primary" busy={make.isPending} onClick={() => make.mutate()}>
                <Sparkles className="size-4" aria-hidden /> Prepare me
              </Button>
            </div>
          ) : (
            <PrepView prep={prep} />
          )}
          <ErrorText error={make.error || query.error} />
          {prep && (
            <Button busy={make.isPending} onClick={() => make.mutate()}>
              Prepare again
            </Button>
          )}
        </div>
      </Card>
    </Collapsible>
  );
}

function Section({ title, hint, children }: { title: string; hint?: string; children: React.ReactNode }) {
  return (
    <section>
      <h3 className="font-semibold text-slate-900">{title}</h3>
      {hint && <p className="mb-2 text-xs text-slate-500">{hint}</p>}
      {children}
    </section>
  );
}

function PrepView({ prep }: { prep: Prep }) {
  return (
    <>
      {prep.note && <Alert tone="info">{prep.note}</Alert>}
      {!prep.used_llm && (
        <p className="text-xs text-slate-500">
          This is the basic prep. With an AI connected (Integrations), you also get stories written from your bullets and questions tailored to this job.
        </p>
      )}

      {(prep.stories ?? []).length > 0 && (
        <Section title="Your stories" hint="Tell each in about two minutes. They use only what's on your resume; practise them out loud.">
          <ul className="space-y-3">
            {prep.stories!.map((s, i) => (
              <li key={i} className="rounded-xl border border-slate-200 p-3">
                <p className="font-medium text-slate-900">{s.title}</p>
                {s.good_for.length > 0 && (
                  <div className="mt-1 flex flex-wrap gap-1">
                    {s.good_for.map((g) => (
                      <Badge key={g}>{g}</Badge>
                    ))}
                  </div>
                )}
                <dl className="mt-2 space-y-1.5">
                  {(["situation", "task", "action", "result"] as const).map((k) => (
                    <div key={k}>
                      <dt className="text-xs font-semibold uppercase tracking-wide text-slate-500">{k}</dt>
                      <dd className="text-slate-700">{s[k]}</dd>
                    </div>
                  ))}
                </dl>
                <details className="mt-2 text-xs text-slate-500">
                  <summary className="cursor-pointer">From your resume</summary>
                  <ul className="mt-1 list-disc pl-4">
                    {s.sources.map((t) => (
                      <li key={t}>{t}</li>
                    ))}
                  </ul>
                </details>
              </li>
            ))}
          </ul>
        </Section>
      )}

      {(prep.questions ?? []).length > 0 && (
        <Section title="Questions they may ask">
          <ul className="space-y-2">
            {prep.questions!.map((q, i) => (
              <li key={i}>
                <span className="text-slate-900">{q.question}</span> <Badge>{q.type}</Badge>
                {q.why && <p className="text-xs text-slate-500">They're checking: {q.why}</p>}
              </li>
            ))}
          </ul>
        </Section>
      )}

      {prep.technical.length > 0 && (
        <Section title="Skills they will probe" hint="For each, what you can point to on your resume.">
          <ul className="space-y-3">
            {prep.technical.map((t) => (
              <li key={t.skill}>
                <p className="text-slate-900">{t.question}</p>
                <ul className="mt-1 list-disc space-y-0.5 pl-5 text-slate-600">
                  {t.your_points.map((p) => (
                    <li key={p.id}>
                      {p.text} <span className="text-xs text-slate-400">({p.where})</span>
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ul>
        </Section>
      )}

      <Section title="Questions about you">
        <ul className="space-y-2">
          {prep.role.map((r) => (
            <li key={r.question}>
              <p className="text-slate-900">{r.question}</p>
              <p className="text-xs text-slate-500">{r.tip}</p>
            </li>
          ))}
        </ul>
      </Section>

      {(prep.stories ?? []).length === 0 && prep.story_starters.length > 0 && (
        <Section title="Turn these into stories" hint="Your strongest bullets for this job. Answer each prompt in a sentence or two.">
          <ul className="space-y-2">
            {prep.story_starters.map((s) => (
              <li key={s.bullet.id} className="rounded-lg bg-slate-50 p-2.5">
                <p className="text-slate-800">{s.bullet.text}</p>
                <p className="mt-1 text-xs text-slate-500">{s.prompts.join(" · ")}</p>
              </li>
            ))}
          </ul>
        </Section>
      )}

      {prep.gaps.length > 0 && (
        <Section title="If they ask about gaps" hint="Honest beats bluffing: interviewers can tell.">
          <ul className="space-y-2">
            {prep.gaps.map((g) => (
              <li key={g.topic}>
                <span className="font-medium text-slate-900">{g.topic}</span>
                <p className="text-slate-600">{g.how_to_answer}</p>
              </li>
            ))}
          </ul>
        </Section>
      )}

      <Section title="Questions to ask them">
        <ul className="list-disc space-y-1 pl-5 text-slate-700">
          {prep.ask.map((a) => (
            <li key={a}>{a}</li>
          ))}
        </ul>
      </Section>
    </>
  );
}

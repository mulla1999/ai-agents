// The scheduler's tasks. They run for every active user; only the superadmin edits them.
// One row per task on wide screens, one card per task on phones.

import { useState } from "react";
import { api } from "../api/client";
import type { ScheduledTask } from "../api/types";
import { Badge, Button, Card, Checkbox, ErrorText, NumberInput, formatDate, useAction } from "./ui";

const TASK_TEXT: Record<string, [string, string]> = {
  discovery: ["Job search", "Searches every enabled job source for each user."],
  outbox: ["Send notifications", "Delivers waiting notification emails."],
  digest: ["Daily summary", "Emails each user their daily summary when it is due."],
  reconcile: ["Check applications", "Re-checks applications whose delivery was uncertain."],
  retention: ["Clean-up", "Removes old logs and warns or deletes inactive accounts."],
};

const GRID = "xl:grid xl:grid-cols-[minmax(0,1.6fr)_8rem_6rem_minmax(0,1fr)_minmax(0,1fr)_minmax(0,1fr)_5rem] xl:items-center xl:gap-3";

export const every = (minutes: number | null) =>
  !minutes ? "—" : minutes % 1440 === 0 ? `every ${minutes / 1440 === 1 ? "day" : `${minutes / 1440} days`}` : minutes % 60 === 0 ? `every ${minutes / 60 === 1 ? "hour" : `${minutes / 60} hours`}` : `every ${minutes} min`;

export function TasksTable({ tasks, editable }: { tasks: ScheduledTask[]; editable: boolean }) {
  return (
    <Card title="Scheduled tasks (all users)">
      <div className={`hidden pb-2 text-xs font-medium uppercase text-slate-500 ${GRID}`}>
        <span>Task</span>
        <span>Every (min)</span>
        <span>On</span>
        <span>Last run</span>
        <span>Next run</span>
        <span>Last result</span>
        <span />
      </div>
      <ul className="divide-y divide-slate-100">
        {tasks.map((t) => (
          <TaskRow key={t.key} task={t} editable={editable} />
        ))}
      </ul>
    </Card>
  );
}

function TaskRow({ task, editable }: { task: ScheduledTask; editable: boolean }) {
  const [interval, setInterval] = useState<number | null>(task.interval_minutes);
  const [enabled, setEnabled] = useState(task.enabled);
  const save = useAction(() => api(`/admin/tasks/${task.key}`, { method: "PUT", body: { interval_minutes: interval ?? 1, enabled } }));
  const [name, about] = TASK_TEXT[task.key] ?? [task.key.replaceAll("_", " "), ""];
  return (
    <li className={`space-y-2 py-3 text-sm xl:space-y-0 ${GRID}`}>
      <div className="min-w-0">
        <p className="font-medium text-slate-900">
          {name} <span className="text-xs font-normal text-slate-500 xl:hidden">· {every(task.interval_minutes)}</span>
        </p>
        {about && <p className="text-xs text-slate-500">{about}</p>}
      </div>
      <label className="flex items-center gap-2 xl:block">
        <span className="w-24 shrink-0 text-xs text-slate-500 xl:hidden">Every (min)</span>
        <NumberInput aria-label={`${name} interval in minutes`} className="w-24" min={1} value={interval} onChange={setInterval} disabled={!editable} />
      </label>
      <div className="flex items-center gap-2">
        <span className="w-24 shrink-0 text-xs text-slate-500 xl:hidden">On</span>
        <Checkbox label="" checked={enabled} onChange={(v) => editable && setEnabled(v)} />
      </div>
      <p className="text-slate-600">
        <span className="mr-2 inline-block w-24 text-xs text-slate-500 xl:hidden">Last run</span>
        {formatDate(task.last_run_at, true)}
      </p>
      <p className="text-slate-600">
        <span className="mr-2 inline-block w-24 text-xs text-slate-500 xl:hidden">Next run</span>
        {formatDate(task.next_run_at, true)}
      </p>
      <div className="min-w-0">
        {task.last_status && <Badge tone={task.last_status === "ok" ? "green" : "red"}>{task.last_status === "ok" ? "worked" : "problem"}</Badge>}
        {task.last_error && <div className="break-words text-xs text-red-700">{task.last_error}</div>}
      </div>
      <div>
        {editable && (
          <Button busy={save.isPending} onClick={() => save.mutate()}>
            Save
          </Button>
        )}
        <ErrorText error={save.error} />
      </div>
    </li>
  );
}

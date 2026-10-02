"use client";

import Link from "next/link";
import { useState } from "react";
import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { PageHeader } from "@/components/ui/PageHeader";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { formatDateTime } from "@/lib/format";
import { useLoad } from "@/lib/hooks/useLoad";
import { m } from "@/messages";
import { ConfirmTypeDialog, typeTitle, type Task } from "./ConfirmTypeDialog";

export function TasksPage() {
  const tasks = useLoad(() => api.GET("/api/v1/me/tasks").then((r) => unwrap(r)), []);
  const taxonomy = useLoad(() => api.GET("/api/v1/taxonomy").then((r) => unwrap(r)), []);
  const [reviewing, setReviewing] = useState<Task | null>(null);
  const [confirmed, setConfirmed] = useState(false);

  const error = tasks.error ?? taxonomy.error;
  const taxonomyData = taxonomy.data;
  return (
    <>
      <PageHeader title={m.tasks.title} />
      <p className="mb-4 text-sm text-muted">{m.tasks.intro}</p>
      {confirmed ? <Alert kind="success">{m.tasks.confirmed}</Alert> : null}
      {error ? (
        <Alert kind="error">
          {error}{" "}
          <Button variant="secondary" onClick={tasks.reload}>
            {m.common.retry}
          </Button>
        </Alert>
      ) : null}
      {!tasks.data || !taxonomyData ? (
        error ? null : (
          <p role="status" className="text-muted">
            {m.app.loading}
          </p>
        )
      ) : tasks.data.length === 0 ? (
        <p className="text-muted">{m.tasks.empty}</p>
      ) : (
        <ul className="space-y-3">
          {tasks.data.map((task) => (
            <li
              key={task.item.id}
              className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border bg-surface p-3"
            >
              <div className="min-w-0 text-sm">
                <p className="truncate font-medium">{task.item.original_name}</p>
                <p className="text-xs text-muted">
                  <Link href={`/projects/${task.project_id}`} className="underline">
                    {task.project_name}
                  </Link>{" "}
                  · {typeTitle(taxonomyData, task.item.selected_doc_type)} · {m.tasks.waitingSince}{" "}
                  {formatDateTime(task.item.updated_at)}
                </p>
              </div>
              <div className="flex items-center gap-2">
                <StatusBadge status={task.item.status} />
                <Button onClick={() => setReviewing(task)}>{m.tasks.review}</Button>
              </div>
            </li>
          ))}
        </ul>
      )}
      {reviewing && taxonomyData ? (
        <ConfirmTypeDialog
          task={reviewing}
          taxonomy={taxonomyData}
          onClose={() => setReviewing(null)}
          onConfirmed={() => {
            setReviewing(null);
            setConfirmed(true);
            tasks.reload();
          }}
        />
      ) : null}
    </>
  );
}

"use client";

import { Alert } from "@/components/ui/Alert";
import { Badge } from "@/components/ui/Badge";
import { Table, Td, Th } from "@/components/ui/Table";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { formatDateTime } from "@/lib/format";
import { useLoad } from "@/lib/hooks/useLoad";
import { m } from "@/messages";

const STATUS_LABEL: Record<string, string> = {
  present: m.gaps.present,
  stub: m.gaps.stub,
  missing: m.gaps.missing,
};
const STATUS_TONE: Record<string, "success" | "warning" | "danger"> = {
  present: "success",
  stub: "warning",
  missing: "danger",
};

export function GapReport({ projectId }: { projectId: string }) {
  const report = useLoad(
    () =>
      api
        .GET("/api/v1/projects/{project_id}/gap-report", {
          params: { path: { project_id: projectId } },
        })
        .then((r) => unwrap(r)),
    [projectId],
  );
  if (report.error) return <Alert kind="error">{report.error}</Alert>;
  if (!report.data) {
    return (
      <p role="status" className="text-muted">
        {m.app.loading}
      </p>
    );
  }
  const data = report.data;
  const percent = Math.round(data.completeness * 100);
  return (
    <div className="space-y-6">
      <p className="text-sm text-muted">{m.gaps.intro}</p>
      <div>
        <p className="font-medium">
          {m.gaps.completeness(data.required_present, data.required_total, percent)}
        </p>
        <div
          role="progressbar"
          aria-label={m.gaps.title}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={percent}
          className="mt-1 h-2 w-full overflow-hidden rounded bg-border"
        >
          <div className="h-full bg-success" style={{ width: `${percent}%` }} />
        </div>
        <p className="mt-1 text-xs text-muted">
          {m.gaps.generated(formatDateTime(data.generated_at))}
        </p>
      </div>
      {data.folders.map((folder) => (
        <section key={folder.id}>
          <h2 className="mb-2 text-sm font-semibold">
            {folder.dir} ({folder.stage})
          </h2>
          <Table caption={`${folder.dir} (${folder.stage})`}>
            <thead>
              <tr>
                <Th>{m.gaps.type}</Th>
                <Th>{m.gaps.required}</Th>
                <Th>{m.gaps.status}</Th>
                <Th>{m.gaps.documents}</Th>
              </tr>
            </thead>
            <tbody>
              {folder.doc_types.map((entry) => (
                <tr key={entry.doc_type}>
                  <Td>{entry.title}</Td>
                  <Td>{entry.required ? m.gaps.required : m.gaps.optional}</Td>
                  <Td>
                    <Badge tone={STATUS_TONE[entry.status]}>{STATUS_LABEL[entry.status]}</Badge>
                  </Td>
                  <Td>{entry.documents}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        </section>
      ))}
    </div>
  );
}

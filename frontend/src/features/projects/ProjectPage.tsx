"use client";

import { useState } from "react";
import { Alert } from "@/components/ui/Alert";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { PageHeader } from "@/components/ui/PageHeader";
import { Tabs } from "@/components/ui/Tabs";
import { DocumentBrowser } from "@/features/documents/DocumentBrowser";
import { GapReport } from "@/features/documents/GapReport";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { useLoad } from "@/lib/hooks/useLoad";
import { m, roleName } from "@/messages";
import { ConsentForm } from "./ConsentForm";
import { MembersPanel } from "./MembersPanel";
import { SettingsPanel } from "./SettingsPanel";
import { INTERNAL_ROLES, type Project } from "./types";

export function ProjectPage({ projectId }: { projectId: string }) {
  const [tab, setTab] = useState("documents");
  const [override, setOverride] = useState<Project | null>(null);
  const loaded = useLoad(
    () =>
      api
        .GET("/api/v1/projects/{project_id}", { params: { path: { project_id: projectId } } })
        .then((r) => unwrap(r, m.projects.notFound)),
    [projectId],
  );
  const project = override ?? loaded.data;

  if (loaded.error) {
    return (
      <Alert kind="error">
        {loaded.error}{" "}
        <Button variant="secondary" onClick={loaded.reload}>
          {m.common.retry}
        </Button>
      </Alert>
    );
  }
  if (!project) {
    return (
      <p role="status" className="text-muted">
        {m.app.loading}
      </p>
    );
  }

  const internal = (INTERNAL_ROLES as readonly string[]).includes(project.my_role);
  const owner = project.my_role === "owner";
  const refresh = () => {
    setOverride(null);
    loaded.reload();
  };

  const overview = (
    <dl className="grid gap-4 sm:grid-cols-2">
      <div>
        <dt className="text-sm text-muted">{m.projects.client}</dt>
        <dd>{project.client_name ?? m.common.none}</dd>
      </div>
      <div>
        <dt className="text-sm text-muted">{m.projects.myRole}</dt>
        <dd>
          <Badge>{roleName(project.my_role)}</Badge>
        </dd>
      </div>
      {project.storage ? (
        <div className="sm:col-span-2">
          <dt className="text-sm text-muted">{m.projects.storage}</dt>
          <dd className="mt-1 grid grid-cols-3 gap-2 rounded-md border border-border p-3 text-sm">
            <span className="text-muted">{m.projects.connection}</span>
            <span className="text-muted">{m.projects.type}</span>
            <span className="text-muted">{m.projects.root}</span>
            <span>{project.storage.connection_name}</span>
            <span>{m.storage.typeLabels[project.storage.type] ?? project.storage.type}</span>
            <span className="font-mono">{project.storage.root}</span>
          </dd>
        </div>
      ) : null}
      <div className="sm:col-span-2">
        <dt className="text-sm text-muted">{m.projects.consentStatus}</dt>
        <dd className="mt-1 space-y-3">
          {project.llm_consent ? (
            <Alert kind="success">
              {m.projects.consentRecorded(
                project.llm_consent.confirmed_by_name,
                new Date(project.llm_consent.confirmed_at).toLocaleDateString("en-GB"),
              )}
            </Alert>
          ) : (
            <>
              <Alert kind="info">{m.projects.consentMissing}</Alert>
              {owner ? <ConsentForm projectId={project.id} onRecorded={refresh} /> : null}
            </>
          )}
        </dd>
      </div>
    </dl>
  );

  return (
    <>
      <PageHeader title={project.name} />
      <Tabs
        label={project.name}
        value={tab}
        onChange={setTab}
        items={[
          {
            id: "documents",
            label: m.documents.title,
            render: () => <DocumentBrowser projectId={project.id} role={project.my_role} />,
          },
          { id: "overview", label: m.projects.overview, render: () => overview },
          ...(internal
            ? [
                {
                  id: "gaps",
                  label: m.gaps.title,
                  render: () => <GapReport projectId={project.id} />,
                },
              ]
            : []),
          ...(internal
            ? [
                {
                  id: "members",
                  label: m.projects.members,
                  render: () => <MembersPanel projectId={project.id} canEdit={owner} />,
                },
              ]
            : []),
          ...(owner
            ? [
                {
                  id: "settings",
                  label: m.projects.settings,
                  render: () => <SettingsPanel project={project} onUpdated={setOverride} />,
                },
              ]
            : []),
        ]}
      />
    </>
  );
}

"use client";

import { useState } from "react";
import { Alert } from "@/components/ui/Alert";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { PageHeader } from "@/components/ui/PageHeader";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { cx } from "@/lib/cx";
import { useLoad } from "@/lib/hooks/useLoad";
import { m, roleName } from "@/messages";
import { ConsentForm } from "./ConsentForm";
import { MembersPanel } from "./MembersPanel";
import { SettingsPanel } from "./SettingsPanel";
import { INTERNAL_ROLES, type Project } from "./types";

type Tab = "overview" | "members" | "settings";

export function ProjectPage({ projectId }: { projectId: string }) {
  const [tab, setTab] = useState<Tab>("overview");
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
  const tabs: { id: Tab; label: string; show: boolean }[] = [
    { id: "overview", label: m.projects.overview, show: true },
    { id: "members", label: m.projects.members, show: internal },
    { id: "settings", label: m.projects.settings, show: owner },
  ];
  const refresh = () => {
    setOverride(null);
    loaded.reload();
  };

  return (
    <>
      <PageHeader title={project.name} />
      <div
        role="tablist"
        aria-label={project.name}
        className="mb-6 flex gap-4 border-b border-border"
      >
        {tabs
          .filter((t) => t.show)
          .map((t) => (
            <button
              key={t.id}
              role="tab"
              type="button"
              aria-selected={tab === t.id}
              onClick={() => setTab(t.id)}
              className={cx(
                "-mb-px border-b-2 px-1 pb-2 text-sm",
                tab === t.id
                  ? "border-brand font-semibold text-brand"
                  : "border-transparent text-muted hover:text-fg",
              )}
            >
              {t.label}
            </button>
          ))}
      </div>
      {tab === "overview" ? (
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
                <span>{project.storage.type}</span>
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
      ) : null}
      {tab === "members" ? <MembersPanel projectId={project.id} canEdit={owner} /> : null}
      {tab === "settings" ? <SettingsPanel project={project} onUpdated={setOverride} /> : null}
    </>
  );
}

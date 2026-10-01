"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { PageHeader } from "@/components/ui/PageHeader";
import { Table, Td, Th } from "@/components/ui/Table";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { useLoad } from "@/lib/hooks/useLoad";
import { useSession } from "@/lib/session/SessionProvider";
import { m, roleName } from "@/messages";
import { CreateProjectDialog } from "./CreateProjectDialog";

export function ProjectsPage() {
  const { me } = useSession();
  const router = useRouter();
  const [creating, setCreating] = useState(false);
  const projects = useLoad(() => api.GET("/api/v1/projects").then((r) => unwrap(r)), []);

  return (
    <>
      <PageHeader
        title={m.projects.title}
        actions={
          me.account_type === "internal" ? (
            <Button onClick={() => setCreating(true)}>{m.projects.newProject}</Button>
          ) : null
        }
      />
      {projects.error ? (
        <Alert kind="error">
          {projects.error}{" "}
          <Button variant="secondary" onClick={projects.reload}>
            {m.common.retry}
          </Button>
        </Alert>
      ) : null}
      {projects.loading ? (
        <p role="status" className="text-muted">
          {m.app.loading}
        </p>
      ) : projects.data && projects.data.length === 0 ? (
        <p className="text-muted">{m.projects.empty}</p>
      ) : projects.data ? (
        <Table caption={m.projects.title}>
          <thead>
            <tr>
              <Th>{m.projects.name}</Th>
              <Th>{m.projects.client}</Th>
              <Th>{m.projects.myRole}</Th>
              <Th>{m.projects.created}</Th>
            </tr>
          </thead>
          <tbody>
            {projects.data.map((project) => (
              <tr key={project.id}>
                <Td>
                  <Link href={`/projects/${project.id}`} className="font-medium text-brand">
                    {project.name}
                  </Link>
                </Td>
                <Td>{project.client_name ?? m.common.none}</Td>
                <Td>{roleName(project.my_role)}</Td>
                <Td>{new Date(project.created_at).toLocaleDateString("en-GB")}</Td>
              </tr>
            ))}
          </tbody>
        </Table>
      ) : null}
      {creating ? (
        <CreateProjectDialog
          onClose={() => setCreating(false)}
          onCreated={(project) => router.push(`/projects/${project.id}`)}
        />
      ) : null}
    </>
  );
}

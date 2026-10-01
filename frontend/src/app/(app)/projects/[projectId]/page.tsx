import { ProjectPage } from "@/features/projects/ProjectPage";

export default async function Page({ params }: PageProps<"/projects/[projectId]">) {
  const { projectId } = await params;
  return <ProjectPage projectId={projectId} />;
}

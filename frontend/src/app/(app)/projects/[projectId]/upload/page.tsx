import { UploadWizard } from "@/features/uploads/UploadWizard";

export default async function Page({ params }: PageProps<"/projects/[projectId]/upload">) {
  const { projectId } = await params;
  return <UploadWizard projectId={projectId} />;
}

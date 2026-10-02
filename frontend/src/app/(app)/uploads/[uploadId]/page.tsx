import { UploadProgress } from "@/features/uploads/UploadProgress";

export default async function Page({ params }: PageProps<"/uploads/[uploadId]">) {
  const { uploadId } = await params;
  return <UploadProgress uploadId={uploadId} />;
}

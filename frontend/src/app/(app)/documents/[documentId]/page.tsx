import { DocumentPage } from "@/features/documents/DocumentPage";

export default async function Page({ params }: PageProps<"/documents/[documentId]">) {
  const { documentId } = await params;
  return <DocumentPage documentId={documentId} />;
}

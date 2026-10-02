import { formatDateTime } from "@/lib/format";
import { m } from "@/messages";

type Frontmatter = Record<string, unknown>;

function text(value: unknown): string {
  if (value === null || value === undefined || value === "") return m.common.none;
  return String(value);
}

/** The converted file's frontmatter (spec 5.3) as a definition list inside a <details>. The
 * document type title and the type-check label are resolved by the caller. */
export function FrontmatterPanel({
  frontmatter,
  typeTitle,
}: {
  frontmatter: Frontmatter;
  typeTitle: string;
}) {
  const typeCheck =
    typeof frontmatter.type_check === "string" ? m.uploads.typeCheck[frontmatter.type_check] : null;
  const uploadedAt =
    typeof frontmatter.uploaded_at === "string"
      ? formatDateTime(frontmatter.uploaded_at)
      : m.common.none;
  const visibility =
    frontmatter.visibility === "shared"
      ? m.documents.shared
      : frontmatter.visibility === "internal"
        ? m.documents.internal
        : text(frontmatter.visibility);
  const rows: [string, string][] = [
    [m.documents.fmTitle, text(frontmatter.title)],
    [m.documents.fmType, typeTitle],
    [m.documents.fmVersion, text(frontmatter.version)],
    [m.documents.fmUploadedBy, text(frontmatter.uploaded_by)],
    [m.documents.fmUploadedAt, uploadedAt],
    [m.documents.fmTypeCheck, typeCheck ?? text(frontmatter.type_check)],
    [m.documents.fmLanguage, text(frontmatter.language)],
    [m.documents.fmVisibility, visibility],
    [m.documents.fmSource, text(frontmatter.source_file)],
    [m.documents.fmKind, text(frontmatter.kind)],
  ];
  return (
    <details
      className="rounded-lg border border-border bg-surface p-3 text-sm"
      aria-label={m.documents.details}
    >
      <summary className="cursor-pointer font-medium">{m.documents.details}</summary>
      <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">
        {rows.map(([label, value]) => (
          <div key={label} className="contents">
            <dt className="text-muted">{label}</dt>
            <dd className="break-words">{value}</dd>
          </div>
        ))}
      </dl>
    </details>
  );
}

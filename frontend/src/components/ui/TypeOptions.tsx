import type { components } from "@/lib/api/schema";

type Taxonomy = components["schemas"]["TaxonomyOut"];

/** Document-type choices grouped by folder (spec 6.1: "dropdown grouped by the six folders");
 * the browser's type-ahead on a native <select> is the search. Render inside a <select>. */
export function TypeOptions({ taxonomy }: { taxonomy: Taxonomy }) {
  return (
    <>
      {taxonomy.folders.map((folder) => (
        <optgroup key={folder.id} label={`${folder.dir} (${folder.stage})`}>
          {folder.doc_types.map((type) => (
            <option key={type.key} value={type.key}>
              {type.title}
            </option>
          ))}
        </optgroup>
      ))}
    </>
  );
}

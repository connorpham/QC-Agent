"use client";

import Markdown from "react-markdown";
import rehypeSanitize, { defaultSchema } from "rehype-sanitize";
import remarkGfm from "remark-gfm";

/** The only place document Markdown is rendered (spec 12, v2.2). Customer uploads are
 * untrusted: react-markdown never emits raw HTML (no rehype-raw), its default urlTransform
 * drops javascript:/data:/vbscript: URLs, and rehype-sanitize's GitHub schema removes every
 * element and attribute outside the allow-list (event handlers, style, iframe, svg, form…).
 * Do not add rehype-raw, a custom schema or dangerouslySetInnerHTML here. */
export function MarkdownView({ markdown }: { markdown: string }) {
  return (
    <div className="markdown">
      <Markdown remarkPlugins={[remarkGfm]} rehypePlugins={[[rehypeSanitize, defaultSchema]]}>
        {markdown}
      </Markdown>
    </div>
  );
}

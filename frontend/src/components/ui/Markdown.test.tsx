import { render } from "@testing-library/react";
import { expect, it } from "vitest";
import { MarkdownView } from "./Markdown";

const HOSTILE = `# Title <script>alert(1)</script>

Para with <img src=x onerror="alert(1)"> and <a href="javascript:alert(1)">x</a>.

[js](javascript:alert(1)) [JS](JaVaScRiPt:alert(1)) [tab](java\tscript:alert(1)) [data](data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==) [vbs](vbscript:msgbox) [ok](https://example.com "t") [rel](../other.md) [mail](mailto:a@example.com) [frag](#section)

![img](javascript:alert(1)) ![ok img](https://example.com/a.png)

<iframe src="https://evil.example"></iframe>
<object data="x"></object><embed src="x">
<svg onload="alert(1)"><circle r=1></svg>
<style>body{display:none}</style>
<div style="position:fixed;top:0" onclick="alert(1)">styled</div>
<form action="https://evil.example"><input name=q></form>
<a href="https://example.com" target="_blank">target</a>

| a | b |
|---|---|
| 1 | <b onmouseover=alert(1)>2</b> |

- [ ] task
- [x] done

~~strike~~ https://autolink.example.com

\`\`\`html
<script>in code block</script>
\`\`\`
`;

it("neutralises scripts, event handlers, dangerous URLs and embedded documents", () => {
  const { container } = render(<MarkdownView markdown={HOSTILE} />);
  const html = container.innerHTML;
  expect(container.querySelector("script")).toBeNull();
  expect(
    container.querySelector("iframe, object, embed, svg, style, form, input[name]"),
  ).toBeNull();
  expect(html).not.toMatch(/on(error|load|click|mouseover)=/i);
  expect(html).not.toMatch(/javascript:/i);
  expect(html).not.toMatch(/vbscript:/i);
  expect(html).not.toMatch(/href="data:/i);
  expect(html).not.toMatch(/ style="/i);
  expect(html).not.toMatch(/target="_blank"/);
  expect(container.querySelector("h1")?.textContent).toBe("Title alert(1)");
  // the hostile image lost its src entirely; the https one is kept
  const images = Array.from(container.querySelectorAll("img"));
  expect(images.map((img) => img.getAttribute("src"))).toEqual([null, "https://example.com/a.png"]);
});

it("keeps safe links, images and GitHub-flavoured Markdown", () => {
  const { container } = render(<MarkdownView markdown={HOSTILE} />);
  const hrefs = Array.from(container.querySelectorAll("a[href]")).map((a) =>
    a.getAttribute("href"),
  );
  expect(hrefs).toEqual([
    "https://example.com",
    "../other.md",
    "mailto:a@example.com",
    "#section",
    "https://autolink.example.com",
  ]); // the raw <a target="_blank"> block is removed entirely, not just its target attribute
  expect(container.querySelector("table thead th")?.textContent).toBe("a");
  expect(container.querySelectorAll("input[type=checkbox]")).toHaveLength(2);
  expect(container.querySelector("del")?.textContent).toBe("strike");
  expect(container.querySelector("pre code")?.textContent).toContain(
    "<script>in code block</script>",
  );
  expect(container.querySelector(".markdown")).not.toBeNull();
});

it("renders plain prose and headings from a converted document", () => {
  const { container } = render(
    <MarkdownView
      markdown={"## Scope\n\nThe system shall allow users to log in.\n\n- MFA\n- Recovery codes"}
    />,
  );
  expect(container.querySelector("h2")?.textContent).toBe("Scope");
  expect(container.querySelectorAll("li")).toHaveLength(2);
});

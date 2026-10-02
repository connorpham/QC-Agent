import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "QC-Agent",
  description: "Project document knowledge base",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    // suppressHydrationWarning: browser extensions commonly add classes and
    // attributes to <html> and <body> before React hydrates (Material Design Lite's
    // "mdl-js", password managers, dark-mode helpers). The mismatch is outside our
    // control and React patches nothing else, so warning on it is pure noise. It
    // suppresses only this element's own attributes, never its children.
    <html lang="en" className="h-full antialiased" suppressHydrationWarning>
      <body className="min-h-full" suppressHydrationWarning>
        {children}
      </body>
    </html>
  );
}

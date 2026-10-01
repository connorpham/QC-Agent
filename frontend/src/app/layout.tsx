import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "QC-Agent",
  description: "Project document knowledge base",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="min-h-full">{children}</body>
    </html>
  );
}

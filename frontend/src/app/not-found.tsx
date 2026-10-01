import Link from "next/link";
import { m } from "@/messages";

export default function NotFound() {
  return (
    <main className="mx-auto max-w-lg p-8 text-center">
      <h1 className="text-2xl font-semibold">{m.app.notFoundTitle}</h1>
      <p className="mt-2 text-muted">{m.app.notFoundBody}</p>
      <Link href="/projects" className="mt-6 inline-block text-brand underline">
        {m.app.backToProjects}
      </Link>
    </main>
  );
}

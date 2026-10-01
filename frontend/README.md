# QC-Agent frontend

Next.js (App Router, TypeScript, Tailwind CSS) web application for QC-Agent. See the repository README for running backend and frontend together.

```bash
pnpm install
pnpm dev          # http://localhost:3000, proxies /api to BACKEND_URL (default http://localhost:8000)
pnpm test         # Vitest + Testing Library
pnpm lint && pnpm format && pnpm typecheck && pnpm build
```

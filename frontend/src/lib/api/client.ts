import createClient, { type Middleware } from "openapi-fetch";
import type { paths } from "./schema";

export const CSRF_HEADER = "X-QC-Agent";
const AUTH_PREFIX = "/api/v1/auth/";

let unauthorizedHandler: (() => void) | null = null;

/** Registered by the session provider: a 401 outside /auth/* means the session is gone. */
export function setUnauthorizedHandler(handler: (() => void) | null): void {
  unauthorizedHandler = handler;
}

/** For request paths that bypass openapi-fetch (the multipart upload). */
export function notifyUnauthorized(): void {
  unauthorizedHandler?.();
}

const csrf: Middleware = {
  onRequest({ request }) {
    if (request.method !== "GET" && request.method !== "HEAD") {
      request.headers.set(CSRF_HEADER, "1");
    }
    return request;
  },
};

const unauthorized: Middleware = {
  onResponse({ request, response }) {
    if (response.status === 401 && !new URL(request.url).pathname.startsWith(AUTH_PREFIX)) {
      unauthorizedHandler?.();
    }
    return response;
  },
};

// Client components also render on the server, where window is undefined; nothing is fetched
// there. In the browser (and jsdom) requests go same-origin through the Next rewrite.
const baseUrl = typeof window === "undefined" ? "http://localhost" : window.location.origin;

export function makeClient(
  fetchImpl: (request: Request) => Promise<Response> = (request) => globalThis.fetch(request),
) {
  const client = createClient<paths>({ baseUrl, fetch: fetchImpl, credentials: "same-origin" });
  client.use(csrf, unauthorized);
  return client;
}

export const api = makeClient();

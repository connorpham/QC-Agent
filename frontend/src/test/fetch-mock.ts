import { vi } from "vitest";

export type Route = {
  method?: string;
  path: string;
  status?: number;
  body?: unknown;
  handler?: (request: Request) => unknown | Promise<unknown>;
};

/** Stub global fetch with routes matched on method + pathname; records every Request. */
export function mockFetch(routes: Route[]) {
  const calls: Request[] = [];
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const request = input instanceof Request ? input : new Request(input, init);
    calls.push(request.clone());
    const url = new URL(request.url);
    const route = routes.find(
      (r) => (r.method ?? "GET") === request.method && r.path === url.pathname,
    );
    if (!route) {
      return new Response(
        JSON.stringify({ detail: `No mock for ${request.method} ${url.pathname}` }),
        { status: 500, headers: { "content-type": "application/json" } },
      );
    }
    const status = route.status ?? 200;
    const body = route.handler ? await route.handler(request) : route.body;
    if (status === 204) return new Response(null, { status });
    return new Response(JSON.stringify(body ?? {}), {
      status,
      headers: { "content-type": "application/json" },
    });
  });
  vi.stubGlobal("fetch", fn);
  return {
    fn,
    calls,
    /** JSON body of the n-th recorded request. */
    body: async (index: number): Promise<unknown> => JSON.parse(await calls[index].text()),
    /** The n-th recorded request matching method + path, if any. */
    find: (method: string, path: string) =>
      calls.find((c) => c.method === method && new URL(c.url).pathname === path),
  };
}

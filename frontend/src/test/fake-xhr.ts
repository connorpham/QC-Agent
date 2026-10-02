import { vi } from "vitest";

type ProgressListener = (event: ProgressEvent) => void;

/** Stand-in for XMLHttpRequest: records open/headers/body, fires one 50% progress event and
 * resolves with `respondWith` (or a network error). jsdom's FormData reaches the test intact,
 * which `fetch`/`Request` cannot offer under jsdom 30 (see the plan's verified behaviour). */
export class FakeXHR {
  static instances: FakeXHR[] = [];
  static respondWith: { status: number; body?: unknown } = { status: 200, body: {} };
  static failWithNetworkError = false;

  static install(): void {
    FakeXHR.instances = [];
    FakeXHR.respondWith = { status: 200, body: {} };
    FakeXHR.failWithNetworkError = false;
    vi.stubGlobal("XMLHttpRequest", FakeXHR);
  }

  method = "";
  url = "";
  headers: Record<string, string> = {};
  body: unknown = null;
  status = 0;
  responseText = "";
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  private progressListeners: ProgressListener[] = [];
  readonly upload = {
    addEventListener: (type: string, listener: ProgressListener) => {
      if (type === "progress") this.progressListeners.push(listener);
    },
  };

  open(method: string, url: string): void {
    this.method = method;
    this.url = url;
  }

  setRequestHeader(name: string, value: string): void {
    this.headers[name] = value;
  }

  send(body: unknown): void {
    this.body = body;
    FakeXHR.instances.push(this);
    if (FakeXHR.failWithNetworkError) {
      queueMicrotask(() => this.onerror?.());
      return;
    }
    for (const listener of this.progressListeners) {
      listener({ lengthComputable: true, loaded: 50, total: 100 } as ProgressEvent);
    }
    this.status = FakeXHR.respondWith.status;
    this.responseText =
      FakeXHR.respondWith.body === undefined ? "" : JSON.stringify(FakeXHR.respondWith.body);
    queueMicrotask(() => this.onload?.());
  }
}

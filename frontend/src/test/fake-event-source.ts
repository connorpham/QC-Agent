import { vi } from "vitest";

type Listener = (event: Event) => void;

/** Stand-in for the browser's EventSource (absent from jsdom): tests open it, emit named
 * events with ids and simulate failures. */
export class FakeEventSource {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSED = 2;
  static instances: FakeEventSource[] = [];

  static install(): void {
    FakeEventSource.instances = [];
    vi.stubGlobal("EventSource", FakeEventSource);
  }

  static get last(): FakeEventSource {
    const last = FakeEventSource.instances.at(-1);
    if (!last) throw new Error("no EventSource was opened");
    return last;
  }

  readonly url: string;
  readyState = FakeEventSource.CONNECTING;
  closed = false;
  private listeners = new Map<string, Set<Listener>>();

  constructor(url: string) {
    this.url = url;
    FakeEventSource.instances.push(this);
  }

  addEventListener(type: string, listener: Listener): void {
    if (!this.listeners.has(type)) this.listeners.set(type, new Set());
    this.listeners.get(type)?.add(listener);
  }

  close(): void {
    this.closed = true;
    this.readyState = FakeEventSource.CLOSED;
  }

  open(): void {
    this.readyState = FakeEventSource.OPEN;
    this.dispatch("open", new Event("open"));
  }

  emit(type: string, data: unknown, lastEventId = ""): void {
    this.dispatch(type, new MessageEvent(type, { data: JSON.stringify(data), lastEventId }));
  }

  /** The browser fires `error` with readyState CONNECTING while it retries, CLOSED when it gave up. */
  fail(readyState: number = FakeEventSource.CONNECTING): void {
    this.readyState = readyState;
    this.dispatch("error", new Event("error"));
  }

  private dispatch(type: string, event: Event): void {
    for (const listener of this.listeners.get(type) ?? []) listener(event);
  }
}

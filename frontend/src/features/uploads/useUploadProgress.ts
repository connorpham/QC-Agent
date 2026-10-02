"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api/client";
import { apiErrorMessage } from "@/lib/api/errors";
import { m } from "@/messages";
import { applyItemEvent, parseItemEvent, parseSettledEvent } from "./events";
import { hasActiveItems, type Upload } from "./types";

export type Connection = "idle" | "connecting" | "live" | "reconnecting" | "polling" | "closed";

/** The subset of EventSource the hook uses (jsdom has none; tests inject a fake). */
export interface EventSourceLike {
  readonly readyState: number;
  addEventListener(type: string, listener: (event: Event) => void): void;
  close(): void;
}

type Options = { pollIntervalMs?: number; createEventSource?: (url: string) => EventSourceLike };
type StreamState = { generation: number; connection: Connection };

const CLOSED = 2; // EventSource.CLOSED
const DEFAULT_POLL_MS = 3000;

/** Live state of one upload: load it, follow `/events` while any item is still being
 * processed, apply `item.status` frames, refresh once on `upload.settled` (and reopen if the
 * refresh still shows active items), fall back to polling when the browser gives up on the
 * stream. The browser's own reconnection (with Last-Event-ID) is left alone.
 *
 * `generation` counts the streams opened; the connection state is recorded per generation
 * and derived at render time, so the effect body never calls a state setter itself (only its
 * listeners do, asynchronously). */
export function useUploadProgress(uploadId: string, options: Options = {}) {
  const pollIntervalMs = options.pollIntervalMs ?? DEFAULT_POLL_MS;
  const createEventSource = options.createEventSource;
  const [upload, setUpload] = useState<Upload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [generation, setGeneration] = useState(0);
  const [stream, setStream] = useState<StreamState>({ generation: 0, connection: "idle" });

  const load = useCallback(async (): Promise<Upload | null> => {
    const { data, error: apiError } = await api.GET("/api/v1/uploads/{upload_id}", {
      params: { path: { upload_id: uploadId } },
    });
    if (!data) {
      setError(apiErrorMessage(apiError, m.uploads.notFound));
      return null;
    }
    setError(null);
    setUpload(data);
    return data;
  }, [uploadId]);

  // initial load; subscribe only when something is still being processed. The bump to
  // `generation` here deliberately triggers the stream-opening effect below — that's the
  // intended cascade (one state change kicking off the subscription), not an accidental one.
  useEffect(() => {
    let cancelled = false;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- intentional: see comment above
    void load().then((data) => {
      if (!cancelled && data && hasActiveItems(data)) setGeneration((g) => g + 1);
    });
    return () => {
      cancelled = true;
    };
  }, [load]);

  // one EventSource per generation
  useEffect(() => {
    if (generation === 0) return;
    const factory = createEventSource ?? ((url: string) => new EventSource(url));
    const source = factory(`/api/v1/uploads/${uploadId}/events`);
    const report = (connection: Connection) => setStream({ generation, connection });
    let polling: ReturnType<typeof setInterval> | null = null;
    let stopped = false;
    const stop = () => {
      // `polling` is cleared unconditionally, even on a repeat call: the effect's cleanup is
      // this same function, and it must still clear the handle on unmount even when a prior
      // `error` handler already set `stopped`.
      if (polling) {
        clearInterval(polling);
        polling = null;
      }
      if (stopped) return;
      stopped = true;
      source.close();
    };
    const finish = (fresh: Upload | null) => {
      if (fresh && hasActiveItems(fresh)) setGeneration((g) => g + 1);
      else report("closed");
    };
    source.addEventListener("open", () => report("live"));
    // On connect and on every reconnect the stream first replays one `item.status` frame per
    // item with its current state; those snapshot frames carry no `id:` line (they must not
    // move the browser's Last-Event-ID), so they are applied exactly like any other frame —
    // nothing here depends on an id being present.
    source.addEventListener("item.status", (event) => {
      const parsed = parseItemEvent(String((event as MessageEvent).data));
      if (parsed) setUpload((current) => (current ? applyItemEvent(current, parsed) : current));
    });
    source.addEventListener("upload.settled", (event) => {
      const settled = parseSettledEvent(String((event as MessageEvent).data));
      if (settled?.items) {
        setUpload((current) => {
          if (!current) return current;
          return settled.items!.reduce((acc, item) => applyItemEvent(acc, item), current);
        });
      }
      stop();
      // The event's `items` are applied above for an immediate, flicker-free update; the
      // refetch still runs so the view also picks up anything the payload left out.
      void load().then(finish);
    });
    source.addEventListener("error", () => {
      if (source.readyState !== CLOSED) {
        report("reconnecting"); // the browser retries with Last-Event-ID by itself
        return;
      }
      stop(); // the browser gave up: poll until nothing is active (and clears any prior handle)
      report("polling");
      polling = setInterval(() => {
        void load().then((fresh) => {
          if (fresh && !hasActiveItems(fresh)) {
            if (polling) clearInterval(polling);
            polling = null;
            report("closed");
          }
        });
      }, pollIntervalMs);
    });
    return stop;
  }, [generation, uploadId, createEventSource, pollIntervalMs, load]);

  const reload = useCallback(() => {
    void load().then((fresh) => {
      if (fresh && hasActiveItems(fresh)) setGeneration((g) => g + 1);
    });
  }, [load]);

  const connection: Connection =
    generation === 0
      ? upload
        ? "closed"
        : "idle"
      : stream.generation === generation
        ? stream.connection
        : "connecting";
  return { upload, error, connection, reload };
}

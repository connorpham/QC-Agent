import { m } from "@/messages";

/** Message from a FastAPI error body: `{"detail": "..."}`, `{"detail": ["...", ...]}` or the
 * 422 shape `{"detail": [{"msg": "...", ...}]}`. */
export function apiErrorMessage(error: unknown, fallback: string): string {
  if (error && typeof error === "object" && "detail" in error) {
    const detail = (error as { detail: unknown }).detail;
    if (typeof detail === "string" && detail) return detail;
    if (Array.isArray(detail)) {
      const parts = detail
        .map((item) => {
          if (typeof item === "string") return item;
          if (item && typeof item === "object" && "msg" in item) {
            return String((item as { msg: unknown }).msg);
          }
          return "";
        })
        .filter((part) => part.length > 0);
      if (parts.length > 0) return parts.join(" ");
    }
  }
  return fallback;
}

/** For loaders: the response data, or an Error carrying the API message. */
export function unwrap<T>(
  result: { data?: T; error?: unknown },
  fallback: string = m.common.loadFailed,
): T {
  if (result.data === undefined) throw new Error(apiErrorMessage(result.error, fallback));
  return result.data;
}

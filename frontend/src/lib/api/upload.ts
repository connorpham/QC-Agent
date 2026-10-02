import { m } from "@/messages";
import { CSRF_HEADER, notifyUnauthorized } from "./client";
import type { components } from "./schema";

export type UploadOut = components["schemas"]["UploadOut"];
export type UploadResponse<T> =
  { ok: true; status: number; data: T } | { ok: false; status: number; error: unknown };

function parse(text: string): unknown {
  if (!text) return null;
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return null;
  }
}

/** Multipart POST over XMLHttpRequest: same-origin (the session cookie travels), CSRF header,
 * upload progress as a fraction, JSON body parsed. Used only for `POST /projects/{id}/uploads`;
 * every other call goes through the typed client. */
export function uploadMultipart<T = UploadOut>(
  path: string,
  form: FormData,
  onProgress?: (fraction: number) => void,
): Promise<UploadResponse<T>> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", path);
    xhr.setRequestHeader(CSRF_HEADER, "1");
    xhr.setRequestHeader("Accept", "application/json");
    xhr.upload.addEventListener("progress", (event) => {
      if (event.lengthComputable && onProgress) onProgress(event.loaded / event.total);
    });
    xhr.onload = () => {
      const body = parse(xhr.responseText);
      if (xhr.status === 401) notifyUnauthorized();
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve({ ok: true, status: xhr.status, data: body as T });
      } else {
        resolve({ ok: false, status: xhr.status, error: body });
      }
    };
    xhr.onerror = () => reject(new Error(m.common.requestFailed));
    xhr.send(form);
  });
}

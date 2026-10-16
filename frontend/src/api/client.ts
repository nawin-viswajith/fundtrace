import type { ApiErrorBody } from "../types/api";

export class ApiError extends Error {
  status: number;
  code: string;
  fields?: string[];
  constructor(status: number, code: string, message: string, fields?: string[]) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.fields = fields;
  }
}

export const UNAUTHORIZED_EVENT = "ft:unauthorized";

function isErrorBody(v: unknown): v is ApiErrorBody {
  return (
    typeof v === "object" &&
    v !== null &&
    "error" in v &&
    typeof (v as ApiErrorBody).error === "object" &&
    typeof (v as ApiErrorBody).error?.message === "string"
  );
}

interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "DELETE";
  body?: unknown;
  form?: FormData;
  signal?: AbortSignal;
  /** Do not broadcast a 401 (used by the session probe and login). */
  quiet401?: boolean;
}

export async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  let body: BodyInit | undefined;
  if (opts.form) body = opts.form;
  else if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.body);
  }
  let res: Response;
  try {
    res = await fetch(path, { method: opts.method ?? "GET", headers, body, credentials: "include", signal: opts.signal });
  } catch (e) {
    if ((e as Error).name === "AbortError") throw e;
    throw new ApiError(0, "network_error", "Could not reach the server. Check your connection and try again.");
  }
  const text = await res.text();
  let data: unknown = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = null;
    }
  }
  if (!res.ok) {
    if (res.status === 401 && !opts.quiet401) window.dispatchEvent(new CustomEvent(UNAUTHORIZED_EVENT));
    if (isErrorBody(data)) throw new ApiError(res.status, data.error.code, data.error.message, data.error.fields);
    throw new ApiError(res.status, "http_" + res.status, `Request failed (${res.status})`);
  }
  return data as T;
}

export function errorMessage(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.fields?.length) return `${e.message}: ${e.fields.join(", ")}`;
    return e.message;
  }
  if (e instanceof Error) return e.message;
  return "Something went wrong";
}

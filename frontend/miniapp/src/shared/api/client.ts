import type { ApiErrorBody } from "./types";

// ── auth context (set once at bootstrap by AuthProvider) ───────────────────
// initDataRaw is the raw, signed init-data string from Telegram — never the
// parsed object. It is attached verbatim as `Authorization: tma <raw>`.
let initDataRaw: string | null = null;
let devBypassTgId: string | null = null;

export function setAuthInitData(raw: string | null): void {
  initDataRaw = raw;
}

export function setDevBypassTgId(tgId: string | null): void {
  devBypassTgId = tgId;
}

export function isDevBypassActive(): boolean {
  return devBypassTgId !== null;
}

// ── typed error ──────────────────────────────────────────────────────────
export class ApiError extends Error {
  readonly status: number;
  readonly body: ApiErrorBody | null;
  readonly headers: Headers;

  constructor(status: number, message: string, body: ApiErrorBody | null, headers: Headers) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
    this.headers = headers;
  }
}

function extractMessage(body: ApiErrorBody | null, fallback: string): string {
  if (!body) return fallback;
  if (typeof body.detail === "string") return body.detail;
  if (body.detail && typeof body.detail === "object" && !Array.isArray(body.detail)) {
    if (body.detail.message) return body.detail.message;
  }
  if (Array.isArray(body.detail) && body.detail[0]?.msg) return body.detail[0].msg as string;
  if (body.message) return body.message;
  return fallback;
}

const API_BASE = "/api/twa";

interface RequestOptions {
  method?: "GET" | "POST";
  body?: unknown;
  signal?: AbortSignal;
}

export async function apiFetch<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = {
    Accept: "application/json",
  };

  if (options.body !== undefined) {
    headers["Content-Type"] = "application/json";
  }

  // Dev bypass takes precedence when active (only ever set in DEV builds
  // behind ?dev=1 — see AuthProvider). This header is NOT implemented by
  // today's backend (app/api/deps.py::twa_identity only accepts the `tma`
  // scheme) — real requests will 403 until that dependency is extended.
  if (devBypassTgId !== null) {
    headers["X-Debug-TgId"] = devBypassTgId;
  } else if (initDataRaw !== null) {
    headers.Authorization = `tma ${initDataRaw}`;
  }

  const res = await fetch(`${API_BASE}${path}`, {
    method: options.method ?? "GET",
    headers,
    body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
    signal: options.signal,
  });

  if (res.status === 204) {
    return undefined as T;
  }

  let parsed: unknown = null;
  const text = await res.text();
  if (text.length > 0) {
    try {
      parsed = JSON.parse(text);
    } catch {
      parsed = null;
    }
  }

  if (!res.ok) {
    const body = parsed as ApiErrorBody | null;
    throw new ApiError(
      res.status,
      extractMessage(body, `Request failed with status ${res.status}`),
      body,
      res.headers,
    );
  }

  return parsed as T;
}

export const api = {
  get: <T>(path: string, signal?: AbortSignal) => apiFetch<T>(path, { method: "GET", signal }),
  post: <T>(path: string, body?: unknown, signal?: AbortSignal) =>
    apiFetch<T>(path, { method: "POST", body: body ?? {}, signal }),
};

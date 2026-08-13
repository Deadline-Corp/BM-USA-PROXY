import axios, { AxiosError, type InternalAxiosRequestConfig } from "axios";
import { useAuthStore } from "@/shared/auth/authStore";
import type { RefreshResponse } from "@/shared/api/types";

export const API_BASE = "/api/admin";

export const apiClient = axios.create({
  baseURL: API_BASE,
  withCredentials: true, // send the httpOnly refresh cookie
});

// Separate instance for the refresh call itself — avoids recursively
// triggering the response interceptor below.
const refreshClient = axios.create({
  baseURL: API_BASE,
  withCredentials: true,
});

apiClient.interceptors.request.use((config) => {
  const token = useAuthStore.getState().accessToken;
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

let refreshInFlight: Promise<string> | null = null;

async function refreshAccessToken(): Promise<string> {
  if (!refreshInFlight) {
    refreshInFlight = refreshClient
      .post<RefreshResponse>("/auth/refresh")
      .then((res) => {
        const token = res.data.access_token;
        useAuthStore.getState().setAccessToken(token);
        return token;
      })
      .finally(() => {
        refreshInFlight = null;
      });
  }
  return refreshInFlight;
}

interface RetriableConfig extends InternalAxiosRequestConfig {
  _retried?: boolean;
}

apiClient.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const original = error.config as RetriableConfig | undefined;

    if (error.response?.status !== 401 || !original || original._retried) {
      throw error;
    }

    // Never try to refresh off the login/refresh endpoints themselves.
    if (
      original.url?.includes("/auth/login") ||
      original.url?.includes("/auth/refresh")
    ) {
      throw error;
    }

    original._retried = true;

    try {
      const token = await refreshAccessToken();
      original.headers = original.headers ?? {};
      original.headers.Authorization = `Bearer ${token}`;
      return apiClient(original);
    } catch (refreshError) {
      useAuthStore.getState().clearSession();
      throw refreshError;
    }
  },
);

/** Extracts a human-readable message from a backend error response,
 * falling back to a generic message. Handles the login rate-limit/lockout
 * case explicitly since the spec calls it out. */
export function apiErrorMessage(error: unknown, fallback = "Something went wrong."): string {
  if (axios.isAxiosError(error)) {
    const data = error.response?.data as
      | { error?: { message?: unknown }; detail?: unknown; message?: unknown }
      | undefined;
    // Every deliberate error this API raises comes back as {"error": {code, message}} —
    // the one shape this function did not read, so all of them arrived as the caller's
    // generic fallback. "Another account already uses this handle" read as "something
    // went wrong", and the reason you could not save was on the wire the whole time.
    const enveloped = data?.error?.message;
    if (typeof enveloped === "string" && enveloped) return enveloped;
    const detail = data?.detail ?? data?.message;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail) && detail.length > 0) {
      const first = detail[0] as { msg?: string } | string;
      if (typeof first === "string") return first;
      if (first?.msg) return first.msg;
    }
    if (error.response?.status === 429) {
      return "Too many attempts. Try again later.";
    }
  }
  return fallback;
}

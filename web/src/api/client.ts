// Thin fetch wrapper: JSON in and out, API errors surfaced with the server's own message.

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

function detail(body: unknown): string | null {
  if (typeof body !== "object" || body === null || !("detail" in body)) return null;
  const value = (body as { detail: unknown }).detail;
  if (typeof value === "string") return value;
  // FastAPI validation errors: a list of {loc, msg}.
  if (Array.isArray(value)) {
    return value
      .map((e: { loc?: unknown[]; msg?: string }) =>
        [e.loc?.slice(1).join("."), e.msg].filter(Boolean).join(": "),
      )
      .join("\n");
  }
  return JSON.stringify(value);
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (response.status === 204) return undefined as T;
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    throw new ApiError(
      response.status,
      detail(body) ?? `${response.status} ${response.statusText}`,
    );
  }
  return body as T;
}

import createClient from "openapi-fetch";
import type { components, paths } from "./schema";

export type Schemas = components["schemas"];

export const client = createClient<paths>({ baseUrl: "" });

let workspaceId: string | null = null;

/** Every request from now on acts in this workspace (the page's /w/{slug}). */
export function actIn(id: string | null) {
  workspaceId = id;
}

// The server refuses writes that lack this header, which a cross-site request cannot add.
// Each request also names its workspace, so a second tab on another workspace never mixes them.
client.use({
  onRequest({ request }) {
    request.headers.set("X-Requested-With", "outbound");
    if (workspaceId) request.headers.set("X-Workspace-Id", workspaceId);
    return request;
  },
});

/**
 * Raised on any 401 from an ordinary request, so the app can show the sign-in page. The sign-in
 * pages' own requests are left out: they are how the app finds out, and reacting to them would
 * loop.
 */
export const SIGNED_OUT = "outbound:signed-out";
client.use({
  onResponse({ response, request }) {
    const asking = new URL(request.url).pathname.startsWith("/api/auth/");
    if (response.status === 401 && !asking) window.dispatchEvent(new Event(SIGNED_OUT));
    return undefined;
  },
});

/** openapi-typescript types an uploaded file as a string; the serializer below sends the real File. */
export const asUpload = (file: File) => file as unknown as string;

/** Send a body with a file in it as multipart form data. */
export function multipart(body: Record<string, unknown>): FormData {
  const data = new FormData();
  for (const [key, value] of Object.entries(body)) {
    if (value === undefined || value === null) continue;
    data.append(key, value instanceof Blob ? value : String(value));
  }
  return data;
}

/** An error answer in the server's problem-details shape. */
export class ApiProblem extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly fields: { field: string; message: string }[] = [],
  ) {
    super(message);
  }
}

type Answer<T> = { data?: T; error?: unknown; response: Response };

/** Unwrap a client answer: return the data, or throw an ApiProblem. */
export async function ok<T>(request: Promise<Answer<T>>): Promise<T> {
  const answer = await request;
  if (answer.error !== undefined || answer.data === undefined) {
    const body = (answer.error ?? {}) as {
      code?: string;
      detail?: string;
      errors?: { field: string; message: string }[];
    };
    throw new ApiProblem(
      answer.response.status,
      body.code ?? "unknown",
      body.detail ?? `Request failed (${answer.response.status})`,
      body.errors ?? [],
    );
  }
  return answer.data;
}

export const isConflict = (error: unknown): boolean =>
  error instanceof ApiProblem && error.status === 409;

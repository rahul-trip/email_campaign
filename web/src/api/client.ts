import createClient from "openapi-fetch";
import type { components, paths } from "./schema";

export type Schemas = components["schemas"];

export const client = createClient<paths>({ baseUrl: "" });

// The server refuses writes that lack this header, which a cross-site request cannot add.
client.use({
  onRequest({ request }) {
    request.headers.set("X-Requested-With", "outbound");
    return request;
  },
});

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

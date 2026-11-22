import { vi } from 'vitest';

export interface RecordedRequest {
  method: string;
  path: string;
  url: string;
  headers: Headers;
  body: unknown;
  credentials: RequestCredentials | undefined;
}

type Handler = (request: RecordedRequest) => Response | Promise<Response>;

/**
 * Replaces global fetch with a small router: `"POST /api/v1/auth/login"` ->
 * handler. Works for RTK Query (fetch(Request)) and plain fetch(url, init).
 * Unknown routes answer 404 so a test never reaches the network.
 */
export function mockFetchRoutes(routes: Record<string, Handler | Handler[]>) {
  const calls: RecordedRequest[] = [];
  const queues = new Map(
    Object.entries(routes).map(([key, value]) => [key, Array.isArray(value) ? [...value] : value]),
  );
  const spy = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
    const request = input instanceof Request ? input : new Request(String(input), init);
    const text = await request.clone().text();
    const recorded: RecordedRequest = {
      method: request.method,
      path: new URL(request.url).pathname,
      url: request.url,
      headers: request.headers,
      body: text ? JSON.parse(text) : undefined,
      credentials: init?.credentials ?? request.credentials,
    };
    calls.push(recorded);
    const entry = queues.get(`${recorded.method} ${recorded.path}`);
    const handler = Array.isArray(entry) ? (entry.length > 1 ? entry.shift() : entry[0]) : entry;
    if (!handler) {
      return new Response(null, { status: 404 });
    }
    return handler(recorded);
  });
  return { calls, spy };
}

/** The first recorded request to `path`; fails the test if there is none. */
export function callTo(calls: RecordedRequest[], path: string): RecordedRequest {
  const call = calls.find((c) => c.path === path);
  if (!call) {
    throw new Error(`No request to ${path}; got: ${calls.map((c) => c.path).join(', ')}`);
  }
  return call;
}

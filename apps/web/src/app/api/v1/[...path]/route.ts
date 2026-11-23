/** Same-origin API proxy: forwards /api/v1/* to the FastAPI backend.
 *
 *  Rationale (docs/DEPLOYMENT_RUNBOOK.md):
 *  - Browsers talk to ONE origin, so cookies/CSRF work without cross-origin
 *    CORS setup and internal Docker hostnames (http://api:8000) never leak
 *    into the browser.
 *  - API_PROXY_TARGET is server-side-only (never shipped to the client).
 *  - Set NEXT_PUBLIC_API_URL to an absolute API origin to bypass the proxy.
 */

import { NextRequest } from "next/server";

const PROXY_TARGET = process.env.API_PROXY_TARGET ?? "http://localhost:8000";

const HOP_BY_HOP = new Set([
  "connection",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
  "host",
]);

async function forward(
  req: NextRequest,
  ctx: { params: Promise<{ path?: string[] }> },
): Promise<Response> {
  const { path = [] } = await ctx.params;
  const target = new URL(
    `${PROXY_TARGET.replace(/\/$/, "")}/api/v1/${path.map(encodeURIComponent).join("/")}`,
  );
  target.search = req.nextUrl.search;

  const headers = new Headers();
  req.headers.forEach((value, name) => {
    if (!HOP_BY_HOP.has(name.toLowerCase()) && name.toLowerCase() !== "cookie") {
      headers.set(name, value);
    }
  });
  const cookie = req.headers.get("cookie");
  if (cookie) headers.set("cookie", cookie);

  const body =
    req.method === "GET" || req.method === "HEAD"
      ? undefined
      : await req.arrayBuffer();

  let upstream: Response;
  try {
    upstream = await fetch(target, {
      method: req.method,
      headers,
      body: body && body.byteLength > 0 ? body : undefined,
      redirect: "manual",
      cache: "no-store",
    });
  } catch {
    return Response.json(
      {
        error: {
          code: "API_UNREACHABLE",
          message: "The NourishRelay API is not reachable. Is the stack running?",
          details: {},
          request_id: "",
        },
      },
      { status: 502 },
    );
  }

  const responseHeaders = new Headers();
  upstream.headers.forEach((value, name) => {
    if (!HOP_BY_HOP.has(name.toLowerCase())) {
      responseHeaders.set(name, value);
    }
  });
  // Preserve EVERY Set-Cookie header verbatim (session + CSRF): constructing
  // Headers from another Headers object collapses duplicates.
  const setCookies =
    typeof upstream.headers.getSetCookie === "function"
      ? upstream.headers.getSetCookie()
      : [];
  if (setCookies.length) {
    responseHeaders.delete("set-cookie");
    for (const cookie of setCookies) {
      responseHeaders.append("set-cookie", cookie);
    }
  }
  const response = new Response(upstream.body, {
    status: upstream.status,
    headers: responseHeaders,
  });
  return response;
}

export const dynamic = "force-dynamic";

export async function GET(req: NextRequest, ctx: { params: Promise<{ path?: string[] }> }) {
  return forward(req, ctx);
}
export async function HEAD(req: NextRequest, ctx: { params: Promise<{ path?: string[] }> }) {
  return forward(req, ctx);
}
export async function POST(req: NextRequest, ctx: { params: Promise<{ path?: string[] }> }) {
  return forward(req, ctx);
}
export async function PATCH(req: NextRequest, ctx: { params: Promise<{ path?: string[] }> }) {
  return forward(req, ctx);
}
export async function PUT(req: NextRequest, ctx: { params: Promise<{ path?: string[] }> }) {
  return forward(req, ctx);
}
export async function DELETE(req: NextRequest, ctx: { params: Promise<{ path?: string[] }> }) {
  return forward(req, ctx);
}

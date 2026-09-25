import { NextRequest, NextResponse } from "next/server";

const ALLOWED = new Set([
  "demo/state", "demo/reset", "agent/message", "sessions/recommend",
  "auth/builder-id/status", "auth/builder-id/start",
  "auth/builder-id/recheck", "live/bootstrap", "live/sessions/recommend", "live/agent/message",
]);

async function forward(request: NextRequest, path: string[]): Promise<NextResponse> {
  const route = path.join("/");
  if (!ALLOWED.has(route)) return NextResponse.json({ detail: "Unsupported route" }, { status: 404 });
  if (request.method === "GET" && !["demo/state", "auth/builder-id/status"].includes(route)) return NextResponse.json({ detail: "Method not allowed" }, { status: 405 });
  if (request.method === "POST" && ["demo/state", "auth/builder-id/status"].includes(route)) return NextResponse.json({ detail: "Method not allowed" }, { status: 405 });
  if ((route.startsWith("auth/") || route.startsWith("live/")) && !["localhost", "127.0.0.1", "::1"].includes(request.nextUrl.hostname)) return NextResponse.json({ detail: "Local attendee access is unavailable" }, { status: 403 });
  if (route === "auth/builder-id/start" || route === "auth/builder-id/recheck" || route.startsWith("live/")) {
    const origin = request.headers.get("origin");
    if (origin) {
      try {
        const originUrl = new URL(origin);
        const loopback = ["localhost", "127.0.0.1", "::1"].includes(originUrl.hostname);
        const samePort = originUrl.port === request.nextUrl.port || (!originUrl.port && !request.nextUrl.port);
        if (!loopback || !samePort) return NextResponse.json({ detail: "Cross-origin sign-in is unavailable" }, { status: 403 });
      } catch {
        return NextResponse.json({ detail: "Cross-origin sign-in is unavailable" }, { status: 403 });
      }
    }
  }
  const base = process.env.PATHFINDER_API_URL ?? "http://127.0.0.1:8000";
  try {
    const upstream = await fetch(`${base.replace(/\/$/, "")}/${route}`, {
      method: request.method,
      headers: request.method === "POST" ? { "Content-Type": "application/json" } : undefined,
      body: request.method === "POST" ? await request.text() : undefined,
      cache: "no-store",
    });
    const body = await upstream.text();
    return new NextResponse(body, { status: upstream.status, headers: { "Content-Type": upstream.headers.get("Content-Type") ?? "application/json" } });
  } catch {
    return NextResponse.json({ detail: "Local Pathfinder API unavailable" }, { status: 502 });
  }
}

export async function GET(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  return forward(request, (await context.params).path);
}

export async function POST(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  return forward(request, (await context.params).path);
}

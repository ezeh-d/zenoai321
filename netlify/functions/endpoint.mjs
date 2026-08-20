// ZENO Anywhere rendezvous.
//
// The owner's PC POSTs its current Cloudflare tunnel URL here; the Netlify
// launcher GETs it and connects. Same-origin, so no CORS and no third party.
//
// SAFETY
//  * Writes require the shared secret ZENO_ANYWHERE_SECRET (a Netlify env var
//    the owner sets). Without it, nobody can change where the launcher points.
//  * The URL must match the trycloudflare.com shape, so even a leaked secret
//    cannot repoint the launcher at an arbitrary phishing domain.
//  * Reads are public: the tunnel URL is not a secret. The ZENO login (owner
//    auth + trusted-device approval) is the gate, not the address.
//
// This function stores a URL string. It cannot reach or control the PC.

import { getStore } from "@netlify/blobs";
import { timingSafeEqual } from "node:crypto";

const SHAPE = /^https:\/\/[a-z0-9-]+\.trycloudflare\.com$/;
const MAX_AGE_MS = 90_000;

function authorized(req) {
  const expected = Buffer.from(`Bearer ${process.env.ZENO_ANYWHERE_SECRET || ""}`);
  const supplied = Buffer.from(req.headers.get("authorization") || "");
  return expected.length > "Bearer ".length && expected.length === supplied.length &&
    timingSafeEqual(expected, supplied);
}

export default async (req) => {
  const store = getStore("zeno-anywhere");

  if (req.method === "GET") {
    let url = (await store.get("url")) || "";
    const updated = (await store.get("updated")) || null;
    const age = Date.now() - Number(updated || 0);
    const stale = !updated || !Number.isFinite(age) || age < 0 || age > MAX_AGE_MS;
    if (stale) url = "";
    return new Response(JSON.stringify({ url, updated, stale }), {
      status: 200,
      headers: { "content-type": "application/json", "cache-control": "no-store" },
    });
  }

  if (req.method === "POST") {
    if (!authorized(req)) {
      return new Response(JSON.stringify({ error: "unauthorized" }), {
        status: 401,
        headers: { "content-type": "application/json" },
      });
    }
    let body;
    const length = Number(req.headers.get("content-length") || 0);
    if (length > 2048) {
      return new Response(JSON.stringify({ error: "request too large" }), { status: 413 });
    }
    try {
      body = await req.json();
    } catch {
      return new Response(JSON.stringify({ error: "bad json" }), { status: 400 });
    }
    const url = String(body.url || "").trim().replace(/\/+$/, "");
    if (!SHAPE.test(url)) {
      return new Response(JSON.stringify({ error: "url shape rejected" }), {
        status: 422,
        headers: { "content-type": "application/json" },
      });
    }
    await store.set("url", url);
    await store.set("updated", String(Date.now()));
    return new Response(JSON.stringify({ ok: true }), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  }

  if (req.method === "DELETE") {
    if (!authorized(req)) {
      return new Response(JSON.stringify({ error: "unauthorized" }), {
        status: 401,
        headers: { "content-type": "application/json" },
      });
    }
    await store.delete("url");
    await store.delete("updated");
    return new Response(JSON.stringify({ ok: true }), {
      status: 200,
      headers: { "content-type": "application/json", "cache-control": "no-store" },
    });
  }

  return new Response(JSON.stringify({ error: "method not allowed" }), {
    status: 405,
    headers: { "content-type": "application/json" },
  });
};

// Routed via an explicit /api/endpoint redirect in netlify.toml (placed before
// the SPA catch-all so it cannot be shadowed) rather than config.path, which
// the greedy /* rewrite can otherwise intercept.

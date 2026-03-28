/**
 * R2 Workspace Cache Worker — Phase 8a
 * Sovereign Sanctuary · Little Nate Infrastructure
 *
 * Cloudflare Worker that provides HTTP API for reading/writing
 * workspace files to R2 storage. Used by the bridge to push file
 * changes and by CLI-Cloud to read when VS Code is disconnected.
 *
 * Deploy: wrangler deploy
 *
 * wrangler.toml bindings:
 *   [[r2_buckets]]
 *   binding = "WORKSPACE"
 *   bucket_name = "sovereign-workspace"
 *
 *   [vars]
 *   AUTH_TOKEN = "your-secret-token"  # Or use wrangler secret
 *
 * File: cloudflare-workers/workspace-cache/src/index.ts
 * Lines: ~90
 */

interface Env {
  WORKSPACE: R2Bucket;
  AUTH_TOKEN: string;
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    // Auth check
    const authHeader = request.headers.get("Authorization");
    if (!authHeader || authHeader !== `Bearer ${env.AUTH_TOKEN}`) {
      return new Response("Unauthorized", { status: 401 });
    }

    const url = new URL(request.url);
    const path = url.pathname;

    // Route: PUT /workspace/{path} — push a file
    if (request.method === "PUT" && path.startsWith("/workspace/")) {
      const key = path.slice(1); // Remove leading /
      const body = await request.text();
      const contentHash = request.headers.get("X-Content-Hash") || "";

      await env.WORKSPACE.put(key, body, {
        customMetadata: {
          contentHash,
          pushedAt: new Date().toISOString(),
          size: String(body.length),
        },
      });

      return Response.json({
        ok: true,
        key,
        size: body.length,
        hash: contentHash,
      });
    }

    // Route: GET /workspace/{path} — read a file
    if (request.method === "GET" && path.startsWith("/workspace/")) {
      // Special: list endpoint
      if (path === "/workspace/_list") {
        const prefix = url.searchParams.get("prefix") || "workspace/";
        const listed = await env.WORKSPACE.list({
          prefix: prefix.startsWith("workspace/") ? prefix : `workspace/${prefix}`,
          limit: 1000,
        });
        const files = listed.objects.map((obj) => obj.key.replace("workspace/", ""));
        return Response.json({ files, count: files.length });
      }

      const key = path.slice(1); // Remove leading /
      const object = await env.WORKSPACE.get(key);

      if (!object) {
        return new Response("Not found", { status: 404 });
      }

      const body = await object.text();
      return new Response(body, {
        headers: {
          "Content-Type": "text/plain; charset=utf-8",
          "X-Content-Hash": object.customMetadata?.contentHash || "",
          "X-Pushed-At": object.customMetadata?.pushedAt || "",
        },
      });
    }

    // Route: DELETE /workspace/{path} — remove a file
    if (request.method === "DELETE" && path.startsWith("/workspace/")) {
      const key = path.slice(1);
      await env.WORKSPACE.delete(key);
      return Response.json({ ok: true, deleted: key });
    }

    return new Response("Not found", { status: 404 });
  },
};

/**
 * SSE Panel Generation Queue Worker
 * Processes panel generation requests from Cloudflare Queue.
 *
 * wrangler.toml:
 *   name = "sse-generation-queue"
 *   main = "generation_queue.js"
 *   [[queues.consumers]]
 *   queue = "sse-panel-generation"
 *
 * Environment bindings:
 *   BACKEND_URL — https://api.sovereignsanctuary.net
 *   BACKEND_SECRET — shared HMAC secret for authenticated calls
 */
export default {
  async queue(batch, env) {
    for (const msg of batch.messages) {
      const { user_id, panel_type } = msg.body;
      // TODO: Call env.BACKEND_URL + "/api/sse/thera-world/preview"
      //       with { user_id, panel_type } and Authorization header
      // TODO: Handle 429 rate-limit — msg.retry() with backoff
      // TODO: Handle 5xx — msg.retry() up to 3 attempts, then ack + log failure
      // TODO: On success, POST result to env.BACKEND_URL + "/api/sse/monitor/log"
      console.log(`[gen-queue] processed user=${user_id} type=${panel_type}`);
      msg.ack();
    }
  },

  async fetch(request, env) {
    return new Response(JSON.stringify({ status: "ok", worker: "sse-generation-queue" }), {
      headers: { "Content-Type": "application/json" },
    });
  },
};

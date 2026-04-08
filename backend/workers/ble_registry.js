/**
 * BLE Device Registry Worker
 * Receives proximity events from mobile devices, matches users by
 * BLE beacon UUID, and forwards co-traveler events to the backend.
 *
 * wrangler.toml:
 *   name = "sse-ble-registry"
 *   main = "ble_registry.js"
 *   [[kv_namespaces]]
 *   binding = "BLE_DEVICES"
 *   id = "<kv-namespace-id>"
 *
 * Environment bindings:
 *   BACKEND_URL — https://api.sovereignsanctuary.net
 *   BACKEND_SECRET — shared HMAC secret
 *   BLE_DEVICES — KV namespace mapping beacon UUIDs to user IDs
 */
export default {
  async fetch(request, env) {
    if (request.method === "POST") {
      const { beacon_uuid, detected_by_user_id } = await request.json();
      // TODO: Look up beacon_uuid in env.BLE_DEVICES KV to resolve nearby_user_id
      // TODO: If match found AND nearby_user_id != detected_by_user_id,
      //       POST to env.BACKEND_URL + "/api/sse-client/ble/proximity"
      //       body: { nearby_user_id }
      //       Headers: Authorization from detected_by_user_id's session token
      // TODO: Rate-limit: max 1 proximity event per pair per 15 minutes (KV TTL)
      // TODO: Return { matched: true/false, deduped: true/false }
      return new Response(JSON.stringify({ status: "received", beacon_uuid }), {
        headers: { "Content-Type": "application/json" },
      });
    }
    return new Response(JSON.stringify({ status: "ok", worker: "sse-ble-registry" }), {
      headers: { "Content-Type": "application/json" },
    });
  },
};

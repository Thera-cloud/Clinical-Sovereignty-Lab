/**
 * Heritage Vault IPFS Pinner Worker
 * Pins heritage vault items to IPFS when crystals reach LOCKED status.
 *
 * wrangler.toml:
 *   name = "sse-ipfs-pinner"
 *   main = "ipfs_pinner.js"
 *   [[queues.consumers]]
 *   queue = "sse-crystal-locked"
 *
 * Environment bindings:
 *   PINATA_JWT — Pinata API JWT for pinning
 *   BACKEND_URL — https://api.sovereignsanctuary.net
 *   BACKEND_SECRET — shared HMAC secret
 */
export default {
  async queue(batch, env) {
    for (const msg of batch.messages) {
      const { crystal_id, crystal_text, user_id } = msg.body;
      // TODO: POST to https://api.pinata.cloud/pinning/pinJSONToIPFS
      //       with { pinataContent: { crystal_id, crystal_text, pinned_at: Date.now() } }
      //       Headers: Authorization: Bearer env.PINATA_JWT
      // TODO: On success, store CID back via
      //       PATCH env.BACKEND_URL + `/api/heritage-vault/crystals/${crystal_id}/ipfs`
      //       body: { ipfs_cid: result.IpfsHash }
      // TODO: On Pinata failure — msg.retry() up to 3 attempts
      // TODO: On success — log to env.BACKEND_URL + "/api/sse/monitor/log"
      console.log(`[ipfs-pinner] pinned crystal=${crystal_id} for user=${user_id}`);
      msg.ack();
    }
  },

  async fetch(request, env) {
    return new Response(JSON.stringify({ status: "ok", worker: "sse-ipfs-pinner" }), {
      headers: { "Content-Type": "application/json" },
    });
  },
};

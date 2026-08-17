/* T1.12 — Bing XML + IndexNow key at www root. No other paths. */
const BING_XML =
  '<?xml version="1.0"?>\n<users>\n\t<user>36351F18F4A42550A7D1CFB2551350C9</user>\n</users>\n';
const INDEXNOW_KEY = "30f24e0be266373675ca6d01227d0ff1";

addEventListener("fetch", (event) => {
  event.respondWith(handle(event.request));
});

function handle(request) {
  const url = new URL(request.url);
  const path = url.pathname;
  if (path !== "/BingSiteAuth.xml" && path !== `/${INDEXNOW_KEY}.txt`) {
    return fetch(request);
  }
  if (request.method !== "GET" && request.method !== "HEAD") {
    return new Response("Method Not Allowed", { status: 405 });
  }
  if (path === "/BingSiteAuth.xml") {
    return new Response(request.method === "HEAD" ? null : BING_XML, {
      status: 200,
      headers: {
        "content-type": "text/xml; charset=utf-8",
        "cache-control": "public, max-age=300",
      },
    });
  }
  return new Response(request.method === "HEAD" ? null : `${INDEXNOW_KEY}\n`, {
    status: 200,
    headers: {
      "content-type": "text/plain; charset=utf-8",
      "cache-control": "public, max-age=300",
    },
  });
}

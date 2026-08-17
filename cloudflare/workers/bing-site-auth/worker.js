/* T1.12 — serve Bing Webmaster XML at www root. No other paths. */
const BODY =
  '<?xml version="1.0"?>\n<users>\n\t<user>36351F18F4A42550A7D1CFB2551350C9</user>\n</users>\n';

addEventListener("fetch", (event) => {
  event.respondWith(handle(event.request));
});

function handle(request) {
  const url = new URL(request.url);
  if (url.pathname !== "/BingSiteAuth.xml") {
    return fetch(request);
  }
  if (request.method !== "GET" && request.method !== "HEAD") {
    return new Response("Method Not Allowed", { status: 405 });
  }
  return new Response(request.method === "HEAD" ? null : BODY, {
    status: 200,
    headers: {
      "content-type": "text/xml; charset=utf-8",
      "cache-control": "public, max-age=300",
    },
  });
}

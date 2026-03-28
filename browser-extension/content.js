(() => {
  "use strict";

  let overlay = null;

  function createOverlay() {
    if (overlay) return overlay;
    overlay = document.createElement("div");
    overlay.id = "nate-overlay";
    overlay.innerHTML = `
      <div class="nate-overlay-header">
        <span class="nate-overlay-title">Little Nate</span>
        <button class="nate-overlay-close">&times;</button>
      </div>
      <div class="nate-overlay-body">
        <div class="nate-overlay-question"></div>
        <div class="nate-overlay-answer"></div>
        <div class="nate-overlay-meta"></div>
      </div>
      <div class="nate-overlay-input-row">
        <input type="text" class="nate-overlay-input" placeholder="Ask Little Nate anything..." />
        <button class="nate-overlay-send">Ask</button>
      </div>
    `;
    document.body.appendChild(overlay);

    overlay
      .querySelector(".nate-overlay-close")
      .addEventListener("click", () => {
        overlay.classList.remove("nate-overlay-visible");
      });

    const input = overlay.querySelector(".nate-overlay-input");
    const sendBtn = overlay.querySelector(".nate-overlay-send");

    function sendQuestion() {
      const q = input.value.trim();
      if (!q) return;
      input.value = "";
      showLoading(q);
      chrome.runtime.sendMessage(
        { type: "ask-nate-inline", question: q, pageUrl: location.href },
        (resp) => {
          showResponse(q, resp);
        }
      );
    }

    sendBtn.addEventListener("click", sendQuestion);
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") sendQuestion();
    });

    return overlay;
  }

  function showLoading(question) {
    const ov = createOverlay();
    ov.querySelector(".nate-overlay-question").textContent = question;
    ov.querySelector(".nate-overlay-answer").innerHTML =
      '<span class="nate-overlay-loading">Thinking...</span>';
    ov.querySelector(".nate-overlay-meta").textContent = "";
    ov.classList.add("nate-overlay-visible");
  }

  function showResponse(question, data) {
    const ov = createOverlay();
    ov.querySelector(".nate-overlay-question").textContent = question;
    ov.querySelector(".nate-overlay-answer").textContent =
      data?.response || "No response received.";
    const meta = [];
    if (data?.queries_remaining != null) {
      meta.push(`${data.queries_remaining} free queries remaining`);
    }
    if (data?.powered_by) {
      meta.push(data.powered_by);
    }
    ov.querySelector(".nate-overlay-meta").textContent = meta.join(" · ");
    ov.classList.add("nate-overlay-visible");
  }

  chrome.runtime.onMessage.addListener((msg) => {
    if (msg.type === "nate-response") {
      showResponse(msg.question, msg.response);
    }
  });

  // Detect @littlenate in text fields
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Enter") return;
    const el = e.target;
    if (
      !el ||
      (el.tagName !== "INPUT" &&
        el.tagName !== "TEXTAREA" &&
        !el.isContentEditable)
    )
      return;

    const text = el.value || el.textContent || "";
    const match = text.match(/@littlenate\s+(.+)/i);
    if (!match) return;

    const question = match[1].trim();
    if (question.length < 2) return;

    e.preventDefault();
    showLoading(question);
    chrome.runtime.sendMessage(
      { type: "ask-nate-inline", question, pageUrl: location.href },
      (resp) => {
        showResponse(question, resp);
      }
    );
  });
})();

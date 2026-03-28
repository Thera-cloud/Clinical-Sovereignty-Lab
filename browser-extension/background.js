const API_BASE = "https://api.sovereignsanctuary.net";

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: "ask-nate",
    title: "Ask Little Nate about this",
    contexts: ["selection"],
  });
  chrome.contextMenus.create({
    id: "ask-nate-page",
    title: "Ask Little Nate about this page",
    contexts: ["page"],
  });
});

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  if (info.menuItemId === "ask-nate" && info.selectionText) {
    const response = await askNate(info.selectionText, tab?.url);
    chrome.tabs.sendMessage(tab.id, {
      type: "nate-response",
      question: info.selectionText,
      response: response,
    });
  }
  if (info.menuItemId === "ask-nate-page" && tab?.url) {
    const response = await askNate(
      `What can you tell me about this page? ${tab.title}`,
      tab.url
    );
    chrome.tabs.sendMessage(tab.id, {
      type: "nate-response",
      question: `About: ${tab.title}`,
      response: response,
    });
  }
});

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.type === "ask-nate-inline") {
    askNate(msg.question, msg.pageUrl).then((resp) => sendResponse(resp));
    return true;
  }
  if (msg.type === "set-token") {
    chrome.storage.local.set({ summon_token: msg.token });
    sendResponse({ ok: true });
    return false;
  }
});

async function askNate(question, pageUrl) {
  const data = await chrome.storage.local.get("summon_token");
  const headers = { "Content-Type": "application/json" };
  if (data.summon_token) {
    headers["Authorization"] = `Bearer ${data.summon_token}`;
  }

  try {
    const resp = await fetch(`${API_BASE}/api/summon`, {
      method: "POST",
      headers,
      body: JSON.stringify({
        message: question.substring(0, 2000),
        channel: "browser_extension",
        context: { page_url: pageUrl || "" },
      }),
    });

    if (!resp.ok) {
      return {
        response: `Connection issue (${resp.status}). Try again.`,
        access_level: "error",
      };
    }

    return await resp.json();
  } catch (e) {
    return {
      response: "Couldn't reach Little Nate. Check your connection.",
      access_level: "error",
    };
  }
}

import {bridgeSettings, collectCookies, ensureCookiePermission, isPairingError, pingLeon, sendToLeon, validWebUrl} from "./bridge.js";

const elements = {
  connection: document.querySelector("#connection"),
  pageTitle: document.querySelector("#pageTitle"),
  pageUrl: document.querySelector("#pageUrl"),
  sendCookies: document.querySelector("#sendCookies"),
  pairingPanel: document.querySelector("#pairingPanel"),
  pairingToken: document.querySelector("#pairingToken"),
  savePairing: document.querySelector("#savePairing"),
  sendOpen: document.querySelector("#sendOpen"),
  sendQueue: document.querySelector("#sendQueue"),
  status: document.querySelector("#status")
};

let currentTab = null;
let themeTimer = null;
const THEMES = new Set(["aurora", "obsidian", "royal_navy", "light", "youtube"]);

function applyTheme(value) {
  if (THEMES.has(value)) document.documentElement.dataset.theme = value;
}

async function syncTheme(pairingToken, response) {
  applyTheme(response?.theme);
  if (THEMES.has(response?.theme)) await chrome.storage.local.set({desktopTheme: response.theme});
  if (themeTimer !== null) clearTimeout(themeTimer);
  themeTimer = setTimeout(async () => {
    try {
      await syncTheme(pairingToken, await pingLeon(pairingToken));
    } catch {
      themeTimer = null;
    }
  }, 4000);
}

function showStatus(message, kind = "") {
  elements.status.textContent = message || "";
  elements.status.className = `status ${kind}`.trim();
}

function connection(message, kind = "") {
  elements.connection.textContent = message;
  elements.connection.className = kind;
}

async function activeTab() {
  const [tab] = await chrome.tabs.query({active: true, lastFocusedWindow: true});
  return tab || null;
}

async function checkConnection() {
  const settings = await bridgeSettings();
  elements.sendCookies.checked = settings.sendCookies;
  elements.pairingPanel.classList.toggle("hidden", Boolean(settings.pairingToken));
  if (!settings.pairingToken) {
    connection("Pairing required", "error");
    return;
  }
  try {
    const response = await pingLeon(settings.pairingToken);
    await syncTheme(settings.pairingToken, response);
    connection("Connected to Leon", "ready");
    elements.pairingPanel.classList.add("hidden");
    await chrome.storage.session.set({autoPopupShown: false});
    await consumePendingSend();
  } catch (error) {
    const pairingProblem = isPairingError(error);
    connection(pairingProblem ? "Pairing required" : "Bridge unavailable", "error");
    elements.pairingPanel.classList.toggle("hidden", !pairingProblem);
    showStatus(error.message || String(error), "error");
  }
}

async function consumePendingSend() {
  const stored = await chrome.storage.session.get("pendingSend");
  const task = stored.pendingSend;
  if (!task || !task.url) return;
  await chrome.storage.session.remove("pendingSend");
  await submit(task.action, {url: task.url, title: task.title || ""});
}

async function submit(action, overrides = {}) {
  const url = validWebUrl(overrides.url || currentTab?.url || "");
  if (!url) {
    showStatus("This tab does not contain a downloadable web URL.", "error");
    return;
  }
  const buttons = [elements.sendOpen, elements.sendQueue];
  buttons.forEach(button => button.disabled = true);
  showStatus("Sending to Leon…");
  try {
    let cookies = [];
    if (elements.sendCookies.checked) {
      const allowed = await ensureCookiePermission(url);
      if (!allowed) throw new Error("Cookie permission was not granted for this site.");
      cookies = await collectCookies(url);
    }
    const response = await sendToLeon({
      action,
      url,
      title: overrides.title || currentTab?.title || "",
      cookies
    });
    const sentLabel = action === "queue" ? "Added to Leon Queue." : "Sent to Leon.";
    if (elements.sendCookies.checked && !response.cookiesSaved) {
      showStatus(`${sentLabel} Chrome returned no usable cookies for this page. Make sure you are signed in and site access was allowed.`, "warning");
    } else {
      const cookieNote = response.cookiesSaved ? ` ${response.cookiesSaved} cookies saved securely.` : "";
      showStatus(`${sentLabel}${cookieNote}`, "ok");
    }
    connection("Connected to Leon", "ready");
  } catch (error) {
    const pairingProblem = isPairingError(error);
    showStatus(error.message || String(error), "error");
    if (pairingProblem) {
      connection("Pairing required", "error");
      elements.pairingPanel.classList.remove("hidden");
    } else {
      const settings = await bridgeSettings();
      connection(settings.pairingToken ? "Connected to Leon" : "Pairing required", settings.pairingToken ? "ready" : "error");
      elements.pairingPanel.classList.toggle("hidden", Boolean(settings.pairingToken));
    }
  } finally {
    buttons.forEach(button => button.disabled = false);
  }
}

elements.sendCookies.addEventListener("change", async () => {
  await chrome.storage.local.set({sendCookies: elements.sendCookies.checked});
});

elements.savePairing.addEventListener("click", async () => {
  const token = elements.pairingToken.value.trim();
  if (!token) {
    showStatus("Paste the pairing code shown in LeonDL.", "error");
    return;
  }
  try {
    const response = await pingLeon(token);
    await chrome.storage.local.set({pairingToken: token});
    await syncTheme(token, response);
    elements.pairingPanel.classList.add("hidden");
    elements.pairingToken.value = "";
    connection("Connected to Leon", "ready");
    showStatus("Pairing completed.", "ok");
  } catch (error) {
    showStatus(error.message || String(error), "error");
  }
});

elements.sendOpen.addEventListener("click", () => submit("open"));
elements.sendQueue.addEventListener("click", () => submit("queue"));

(async () => {
  const storedTheme = await chrome.storage.local.get({desktopTheme: 'youtube'});
  applyTheme(storedTheme.desktopTheme);
  currentTab = await activeTab();
  elements.pageTitle.textContent = currentTab?.title || "Current page";
  elements.pageUrl.textContent = currentTab?.url || "";
  await checkConnection();
})();

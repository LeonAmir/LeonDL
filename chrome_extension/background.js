import {bridgeSettings, collectCookies, ensureCookiePermission, sendToLeon, validWebUrl} from "./bridge.js";

const MENU_ROOT = "leon-root";
const MENU_OPEN = "leon-open";
const MENU_QUEUE = "leon-queue";

async function rebuildMenus() {
  await chrome.contextMenus.removeAll();
  chrome.contextMenus.create({
    id: MENU_ROOT,
    title: "LeonDL",
    contexts: ["page", "link", "video", "audio"]
  });
  chrome.contextMenus.create({
    id: MENU_OPEN,
    parentId: MENU_ROOT,
    title: "Send to Leon",
    contexts: ["page", "link", "video", "audio"]
  });
  chrome.contextMenus.create({
    id: MENU_QUEUE,
    parentId: MENU_ROOT,
    title: "Add to Leon Queue",
    contexts: ["page", "link", "video", "audio"]
  });
}

chrome.runtime.onInstalled.addListener(rebuildMenus);
chrome.runtime.onStartup.addListener(rebuildMenus);

function targetFromClick(info, tab) {
  const mediaFirst = info.mediaType === "video" || info.mediaType === "audio";
  const candidates = mediaFirst
    ? [info.srcUrl, info.linkUrl, info.frameUrl, info.pageUrl, tab?.url]
    : [info.linkUrl, info.srcUrl, info.frameUrl, info.pageUrl, tab?.url];
  for (const candidate of candidates) {
    const valid = validWebUrl(candidate || "");
    if (valid) return valid;
  }
  return "";
}

async function cookiesForUserAction(url) {
  const settings = await bridgeSettings();
  if (!settings.sendCookies) return [];
  const allowed = await ensureCookiePermission(url);
  if (!allowed) throw new Error("Cookie permission was not granted for this site.");
  return collectCookies(url);
}

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  if (info.menuItemId !== MENU_OPEN && info.menuItemId !== MENU_QUEUE) return;
  const url = targetFromClick(info, tab);
  if (!url) return;
  try {
    const settings = await bridgeSettings();
    const cookies = await cookiesForUserAction(url);
    const response = await sendToLeon({
      action: info.menuItemId === MENU_QUEUE ? "queue" : "open",
      url,
      title: tab?.title || "",
      cookies
    });
    const missingCookies = settings.sendCookies && !response.cookiesSaved;
    await chrome.action.setBadgeBackgroundColor({color: missingCookies ? "#C47A00" : "#2BAA66"});
    await chrome.action.setBadgeText({text: missingCookies ? "0" : "✓"});
  } catch (error) {
    console.error("Leon bridge error", error);
    await chrome.action.setBadgeBackgroundColor({color: "#D93025"});
    await chrome.action.setBadgeText({text: "!"});
    // First use: Chrome only shows the native-messaging permission prompt from
    // an extension PAGE, not from a context-menu click. Surface the popup (the
    // click is a user gesture) so the permission prompt can appear; the popup
    // then re-sends this request automatically once approved.
    const session = await chrome.storage.session.get({autoPopupShown: false});
    if (!session.autoPopupShown) {
      await chrome.storage.session.set({
        autoPopupShown: true,
        pendingSend: {
          action: info.menuItemId === MENU_QUEUE ? "queue" : "open",
          url,
          title: tab?.title || ""
        }
      });
      chrome.action.openPopup?.().catch?.(() => {});
    }
  }
  setTimeout(() => chrome.action.setBadgeText({text: ""}), 1800);
});

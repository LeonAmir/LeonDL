export const HOST_NAME = "com.leon_downloader.bridge";

const KNOWN_DOMAINS = [
  "youtube.com", "instagram.com", "facebook.com", "tiktok.com",
  "twitter.com", "x.com", "reddit.com", "soundcloud.com",
  "spotify.com", "vimeo.com", "twitch.tv"
];

export function validWebUrl(value) {
  try {
    const url = new URL(value);
    return (url.protocol === "http:" || url.protocol === "https:") ? url.href : "";
  } catch {
    return "";
  }
}

export function serviceDomain(value) {
  const url = new URL(value);
  let host = url.hostname.toLowerCase().replace(/^www\./, "").replace(/^m\./, "").replace(/^music\./, "");
  for (const known of KNOWN_DOMAINS) {
    if (host === known || host.endsWith(`.${known}`)) {
      return known;
    }
  }
  const parts = host.split(".");
  if (parts.length <= 2) return host;
  const suffix = parts.slice(-2).join(".");
  const twoLevel = new Set(["co.uk", "com.au", "co.jp", "co.in", "com.br", "com.tr"]);
  return twoLevel.has(suffix) && parts.length >= 3 ? parts.slice(-3).join(".") : suffix;
}

export function permissionOrigins(url) {
  const parsed = new URL(url);
  const domain = serviceDomain(url);
  const scheme = parsed.protocol === "http:" ? "http" : "https";
  const origins = [`${scheme}://${domain}/*`];
  if (domain.includes(".")) origins.push(`${scheme}://*.${domain}/*`);
  return origins;
}

export async function ensureCookiePermission(url) {
  const origins = permissionOrigins(url);
  if (await chrome.permissions.contains({origins})) return true;
  try {
    return Boolean(await chrome.permissions.request({origins}));
  } catch (error) {
    const detail = error?.message || String(error || "");
    throw new Error(`Chrome could not grant cookie access for this site: ${detail}`);
  }
}

export async function collectCookies(url) {
  // URL-scoped lookup returns only cookies that are actually applicable to the
  // page being sent. Leon performs a second domain filter before persistence.
  return chrome.cookies.getAll({url});
}

export function isPairingError(error) {
  const message = String(error?.message || error || "").toLowerCase();
  return message.includes("pairing code") || message.includes("pairing token") || message.includes("invalid pairing");
}

export async function bridgeSettings() {
  const values = await chrome.storage.local.get({
    pairingToken: "",
    sendCookies: true
  });
  return {
    pairingToken: String(values.pairingToken || "").trim(),
    sendCookies: Boolean(values.sendCookies)
  };
}

export async function sendToLeon({action, url, title, cookies = []}) {
  const settings = await bridgeSettings();
  if (!settings.pairingToken) {
    throw new Error("Pairing code is not configured. Open the extension popup and paste the code from LeonDL.");
  }
  const response = await chrome.runtime.sendNativeMessage(HOST_NAME, {
    type: "submit",
    action,
    url,
    title: title || "",
    cookies,
    pairingToken: settings.pairingToken,
    extensionVersion: chrome.runtime.getManifest().version
  });
  if (!response || response.ok !== true) {
    throw new Error(response?.error || "LeonDL did not accept the request.");
  }
  return response;
}

export async function pingLeon(pairingToken = "") {
  const settings = await bridgeSettings();
  const token = pairingToken || settings.pairingToken;
  if (!token) throw new Error("Pairing code is missing.");
  const response = await chrome.runtime.sendNativeMessage(HOST_NAME, {
    type: "ping",
    pairingToken: token
  });
  if (!response || response.ok !== true) {
    throw new Error(response?.error || "LeonDL bridge is unavailable.");
  }
  return response;
}

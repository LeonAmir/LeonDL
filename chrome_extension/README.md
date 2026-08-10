# LeonDL Chrome Extension

1. Open LeonDL and select **Chrome Extension**.
2. Click **Install / Repair Bridge**.
3. Open `chrome://extensions`, enable Developer mode, click **Load unpacked**, and select the extension folder shown by Leon.
4. Copy the pairing code from Leon and paste it into the extension popup once.

The extension can send the active page or a right-clicked page/link/media URL to Leon. Cookie access is optional and requested per site. Cookies are sent only to the local native host and are stored through Leon's authentication store.

## Leon authentication source

When **Send site cookies** is enabled and a page is sent, Leon stores the accepted same-site cookies as the distinct `extension` authentication source for that domain. It can be selected from Settings → Cookies and login.

## Updating the unpacked extension

After replacing Leon with a newer version, open `chrome://extensions` and press **Reload** on LeonDL Bridge. The pairing code remains in `chrome.storage.local`; ordinary cookie-permission failures must not require pairing again. Popup and context-menu sends request site access only during the user's click.

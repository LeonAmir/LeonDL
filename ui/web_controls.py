"""The HTML/CSS/JS controls shared across LeonDL's existing theme palettes."""
from __future__ import annotations

import json

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

try:
    from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
    from PySide6.QtWebEngineWidgets import QWebEngineView
except ImportError:
    QWebEngineView = None


_DOCUMENT = """<!doctype html><html><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'">
<style>
:root{font:14px 'Segoe UI',Tahoma,sans-serif;color:var(--text)}
*{box-sizing:border-box}body{background:transparent;margin:0;padding:4px 8px 6px;overflow:hidden}
.number{font-weight:700;font-size:34px;line-height:1;letter-spacing:-.5px;font-variant-numeric:tabular-nums;margin-block:2px 8px}
.track{height:17px;border-radius:99px;background:var(--field);border:1px solid var(--line);overflow:hidden}
.fill{height:100%;border-radius:99px;background:linear-gradient(90deg,var(--accent),var(--end));box-shadow:0 0 12px var(--accent);transition:width .22s ease}
.track.busy .fill{width:36%!important;animation:pulse 1.1s alternate infinite ease-in-out}
@keyframes pulse{from{opacity:.3}to{opacity:1}}
@media(prefers-reduced-motion:reduce){.fill{transition:none}.track.busy .fill{animation:none}}
.usage{display:flex;align-items:center;gap:18px}.dial{width:155px;position:relative;flex:none;text-align:center}
svg{display:block;width:100%}.arc{stroke:var(--accent);filter:drop-shadow(0 0 5px var(--accent))}
.amount{position:absolute;inset:auto 0 5px;font-weight:680;font-size:21px}.caption{color:var(--muted);font-size:12px}
.volume{position:relative;margin:25px 4px 0;direction:ltr}.value{position:absolute;left:clamp(16px,calc(var(--position)*1%),calc(100% - 16px));transform:translateX(-50%);top:-21px;background:var(--accent);color:var(--accentText);padding:3px 7px;border-radius:99px;font-size:11px;pointer-events:none}
input{appearance:none;width:100%;height:24px;margin:0;cursor:pointer;background:transparent}
input::-webkit-slider-runnable-track{height:15px;border:1px solid var(--line);border-radius:99px;background:repeating-linear-gradient(90deg,transparent 0 calc(10% - 1px),var(--accent) calc(10% - 1px) 10%) center 2px/92% 4px no-repeat,var(--field)}
input::-webkit-slider-thumb{appearance:none;width:19px;height:23px;margin-top:-5px;border:1px solid var(--line);border-radius:7px;background:linear-gradient(var(--accent),var(--accent)) center/2px 14px no-repeat,var(--surface)}
input:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.scale{display:flex;justify-content:space-between;color:var(--muted);font-size:10px}
</style></head><body><main id="surface"></main><script>
const surface=document.querySelector('#surface');
let kind='';
function display(next, state){
 if(next!==kind){
  kind=next;
  if(kind==='progress')surface.innerHTML='<div class="number"><bdi></bdi></div><div class="track" role="progressbar" aria-valuemin="0" aria-valuemax="100"><div class="fill"></div></div>';
  if(kind==='usage')surface.innerHTML='<div class="usage"><div class="dial"><svg viewBox="0 0 232 124" aria-hidden="true"><path class="arc" d="M20 116 A96 96 0 0 1 212 116" fill="none" stroke-width="6" stroke-linecap="round"/></svg><div class="amount"><bdi></bdi></div></div><div><strong></strong><div class="caption"></div></div></div>';
  if(kind==='volume'){
   surface.innerHTML='<div class="volume"><output class="value" for="volume"></output><input id="volume" type="range" min="0" max="100"><div class="scale" aria-hidden="true"><span>0</span><span>25</span><span>50</span><span>75</span><span>100</span></div></div>';
   surface.querySelector('input').addEventListener('input',event=>{
    volume(Number(event.target.value));
    console.info('leondl-volume:'+event.target.value);
   });
  }
 }
 document.documentElement.dir=state.dir;
 document.documentElement.lang=state.lang;
 for(const [key,value] of Object.entries(state.colors))document.documentElement.style.setProperty('--'+key,value);
 if(kind==='progress'){
  surface.querySelector('bdi').textContent=state.text;
  const track=surface.querySelector('.track');
  track.classList.toggle('busy',state.percent===null);
  track.setAttribute('aria-label',state.label);
  if(state.percent===null)track.removeAttribute('aria-valuenow');else track.setAttribute('aria-valuenow',state.percent);
  surface.querySelector('.fill').style.width=(state.percent||0)+'%';
 }
 if(kind==='usage'){
  surface.querySelector('bdi').textContent=state.text;
  surface.querySelector('strong').textContent=state.label;
  surface.querySelector('.caption').textContent=state.caption;
 }
 if(kind==='volume'){
  const input=surface.querySelector('input');
  input.value=state.value;input.disabled=state.disabled;
  input.setAttribute('aria-label',state.label);
  volume(state.value);
 }
}
function volume(value){
 surface.querySelector('.volume').style.setProperty('--position',value);
 surface.querySelector('output').textContent=value+'%';
}
</script></body></html>"""


if QWebEngineView is not None:
    class _ControlPage(QWebEnginePage):
        volume_changed = Signal(int)

        def javaScriptConsoleMessage(self, _level, message, _line, _source):
            prefix = "leondl-volume:"
            if message.startswith(prefix) and message[len(prefix):].isdecimal():
                value = int(message[len(prefix):])
                if 0 <= value <= 100:
                    self.volume_changed.emit(value)


    class _ControlView(QWebEngineView):
        ready = Signal()

        def __init__(self, kind: str, height: int, parent=None):
            super().__init__(parent)
            self.kind = kind
            self.state = {}
            self.loaded = False
            self.setFixedHeight(height)
            self.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
            page = _ControlPage(self)
            page.setBackgroundColor(QColor(Qt.GlobalColor.transparent))
            self.setPage(page)
            settings = page.settings()
            settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, False)
            settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False)
            self.loadFinished.connect(self._loaded)
            self.setHtml(_DOCUMENT)

        def _loaded(self, ok: bool):
            self.loaded = ok
            if ok:
                self._display()
                self.ready.emit()

        def set_state(self, **state):
            self.state.update(state)
            if self.loaded:
                self._display()

        def _display(self):
            if "colors" in self.state:
                self.page().runJavaScript(f"display({json.dumps(self.kind)}, {json.dumps(self.state)})")

        def set_theme(self, theme, language: str):
            colors = {
                "text": theme.text, "muted": theme.muted, "line": theme.border,
                "field": theme.progress_bg, "accent": theme.accent, "end": theme.primary_end,
                "accentText": theme.accent_text, "surface": theme.surface,
            }
            self.set_state(colors=colors, dir="rtl" if language == "fa" else "ltr", lang=language)


def web_control(kind: str, height: int, parent=None):
    app = QApplication.instance()
    if QWebEngineView is None or app is None or app.platformName() in {"offscreen", "minimal"}:
        return None
    return _ControlView(kind, height, parent)

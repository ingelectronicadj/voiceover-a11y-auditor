"""Control de VoiceOver en macOS escritorio: cursor lineal, panel de caption y captura de ventana.

Usa `osascript` (System Events) para sintetizar los atajos de VoiceOver y para leer los
textos estaticos del panel de caption del proceso `VoiceOver` (lo que VO esta diciendo),
sin OCR. Las capturas de pantalla usan `screencapture -R` sobre la ventana del navegador,
que incluye el recuadro de foco de VoiceOver al ser un overlay del sistema.

Requiere en el host (Terminal / Devin / app lanzadora):
  - Permiso de Accesibilidad (System Events: envio de teclas y UI scripting).
  - Permiso de Grabacion de Pantalla (screencapture con contenido de otras apps).
"""

import json
import os
import subprocess
import time

# VO + flecha derecha / izquierda (movimiento lineal del cursor de VoiceOver)
_KEY_RIGHT = 124
_KEY_LEFT = 123
# Cmd+F5 alterna VoiceOver on/off
_KEY_F5 = 96


def _osascript(script, lang="AppleScript", timeout=20):
    try:
        res = subprocess.run(
            ["osascript", "-l", lang, "-e", script],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return res.stdout.strip(), res.stderr.strip(), res.returncode
    except subprocess.TimeoutExpired:
        return "", "osascript timeout", 1


def ax_is_trusted():
    """True si el proceso lanzador tiene permiso de Accesibilidad (UI scripting/teclas)."""
    out, _, rc = _osascript(
        'tell application "System Events" to get UI elements enabled', timeout=10
    )
    return rc == 0 and out.lower() == "true"


def screen_recording_ok():
    """True si `screencapture` puede capturar regiones (permiso Grabacion de Pantalla)."""
    import tempfile
    fd, p = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    res = subprocess.run(
        ["screencapture", "-x", "-R0,0,8,8", p], capture_output=True, text=True
    )
    ok = res.returncode == 0 and os.path.exists(p) and os.path.getsize(p) > 100
    try:
        os.remove(p)
    except OSError:
        pass
    return ok


def tcc_preflight():
    """Devuelve lista de permisos macOS faltantes con instrucciones."""
    missing = []
    if not ax_is_trusted():
        missing.append(
            "Accesibilidad: el proceso lanzador no puede enviar teclas ni leer la UI de "
            "otras apps. Concedelo en Ajustes del Sistema > Privacidad y Seguridad > "
            "Accesibilidad (Terminal / Devin / iTerm segun desde donde lances vo_web.py)."
        )
    if not screen_recording_ok():
        missing.append(
            "Grabacion de Pantalla: screencapture no puede capturar. Concedelo en "
            "Ajustes del Sistema > Privacidad y Seguridad > Grabacion de Pantalla."
        )
    return missing


def vo_is_running():
    out, _, rc = _osascript(
        'tell application "System Events" to exists process "VoiceOver"', timeout=10
    )
    return rc == 0 and out.lower() == "true"


def vo_set_enabled(enabled):
    """Activa o desactiva VoiceOver. ON: abre VoiceOver.app directamente (no requiere
    permiso de teclas). OFF: intenta Cmd+F5 y si no hay permiso, mata el proceso."""
    enabled = bool(enabled)
    if vo_is_running() == enabled:
        return True
    if enabled:
        subprocess.run(
            ["open", "/System/Library/CoreServices/VoiceOver.app"], capture_output=True
        )
    else:
        _, _, rc = _osascript(
            'tell application "System Events" to key code %d using command down' % _KEY_F5
        )
        if rc != 0:
            subprocess.run(["killall", "VoiceOver"], capture_output=True)
    for _ in range(10):
        time.sleep(1.0)
        if vo_is_running() == enabled:
            return True
    return False


def bring_app_front(app_name="Google Chrome"):
    _osascript('tell application "%s" to activate' % app_name, timeout=10)
    time.sleep(0.8)


def vo_move_cursor(backward=False, repeat=1):
    """Avanza el cursor de VoiceOver (VO+flecha). Devuelve True si el envio no dio error."""
    code = _KEY_LEFT if backward else _KEY_RIGHT
    ok = True
    for _ in range(max(1, repeat)):
        _, err, rc = _osascript(
            'tell application "System Events" to key code %d using {control down, option down}'
            % code,
            timeout=8,
        )
        ok = ok and rc == 0
    return ok


# Recorrido recursivo de todas las ventanas del proceso VoiceOver recolectando AXStaticText.
# El panel de caption muestra lo que VO esta hablando (incluidos anuncios de live regions).
_CAPTION_JXA = r"""
const se = Application("System Events");
const texts = [];
try {
  const procs = se.processes.whose({name: "VoiceOver"});
  if (procs.length) {
    const p = procs[0];
    function walk(el) {
      try {
        if (el.role() === "AXStaticText") {
          const v = el.value();
          if (typeof v === "string" && v.trim()) texts.push(v.trim());
        }
      } catch (e) {}
      try { el.uiElements().forEach(walk); } catch (e) {}
    }
    p.windows().forEach(w => walk(w));
  }
} catch (e) {}
JSON.stringify(texts);
"""


def vo_caption_texts():
    """Devuelve la lista de textos estaticos visibles en las ventanas de VoiceOver
    (panel de caption + panel de braille). Cadena vacia -> []."""
    out, _, rc = _osascript(_CAPTION_JXA, lang="JavaScript", timeout=20)
    if rc != 0 or not out:
        return []
    try:
        data = json.loads(out)
        return [t for t in data if isinstance(t, str)]
    except Exception:
        return []


def vo_caption():
    """Texto principal del panel de caption (el estatico mas largo visible)."""
    texts = vo_caption_texts()
    if not texts:
        return ""
    return max(texts, key=len)


def app_window_rect(app_name="Google Chrome"):
    """Bounds de la ventana frontal de la app -> (x, y, w, h) o None."""
    out, _, rc = _osascript(
        'tell application "%s" to get bounds of front window' % app_name, timeout=10
    )
    if rc != 0 or not out:
        return None
    try:
        x1, y1, x2, y2 = [int(float(t.strip())) for t in out.split(",")[:4]]
        return x1, y1, max(1, x2 - x1), max(1, y2 - y1)
    except Exception:
        return None


def capture_window(out_png, app_name="Google Chrome"):
    """Captura la ventana frontal de la app (incluye el recuadro de foco de VO)."""
    rect = app_window_rect(app_name)
    if not rect:
        return False
    x, y, w, h = rect
    res = subprocess.run(
        ["screencapture", "-x", "-R%d,%d,%d,%d" % (x, y, w, h), out_png],
        capture_output=True,
    )
    return res.returncode == 0 and os.path.exists(out_png)


def poll_captions(stop_flag, sink, interval=0.35):
    """Sondea el panel de caption hasta que stop_flag() sea True; acumula textos
    distintos con timestamp relativo en `sink` (lista de dicts)."""
    t0 = time.time()
    seen = set()
    while not stop_flag():
        txt = vo_caption()
        if txt and txt not in seen:
            seen.add(txt)
            sink.append({"t": round(time.time() - t0, 2), "text": txt})
        time.sleep(interval)

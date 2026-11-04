"""Preflight del entorno (--doctor) y diagnostico de red para SSO/CDN (iOS)."""

import os
import socket
import subprocess
import sys
from urllib.parse import urlparse

from . import VERSION
from .config import SCRIPT_DIR


def probe_host(url, timeout=5):
    """TCP probe al host:puerto de `url`. Devuelve (ok, detalle)."""
    p = urlparse(url if "://" in url else "https://" + url)
    host = p.hostname or url
    port = p.port or (443 if p.scheme == "https" else 80)
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, "conecta"
    except socket.gaierror:
        return False, "%s no resuelve DNS" % host
    except (socket.timeout, TimeoutError):
        return False, "%s:%d timeout" % (host, port)
    except ConnectionRefusedError:
        return False, "%s:%d conexión rechazada" % (host, port)
    except OSError as e:
        return False, "%s: %s" % (host, e)


def net_hint(url):
    """Pista accionable según el dominio que falló."""
    host = urlparse(url if "://" in url else "https://" + url).hostname or ""
    if ".corp" in host or ".sar." in host or host.endswith(".internal"):
        return "dominio interno -> requiere VPN corporativa activa"
    return "revisa conectividad de red / VPN"


def check_sso_endpoints(cfg, timeout=5):
    """Sondea los endpoints del perfil y devuelve los inalcanzables como
    lista de (key, url, detalle_fallo)."""
    bad = []
    for key in ("login_url", "sso_url", "hybrid_cdn_url"):
        url = (cfg or {}).get(key, "")
        if not url:
            continue
        ok, det = probe_host(url, timeout=timeout)
        if not ok:
            bad.append((key, url, det))
    return bad


def friendly_net_error(e, url):
    """Traduce errores urllib/socket a una causa accionable."""
    import urllib.error

    host = urlparse(url).hostname or url
    reason = getattr(e, "reason", e)
    if isinstance(reason, socket.gaierror):
        return "%s no resuelve DNS -> %s" % (host, net_hint(url))
    if isinstance(reason, (socket.timeout, TimeoutError)) or "timed out" in str(reason):
        return "timeout conectando a %s -> %s" % (host, net_hint(url))
    if isinstance(reason, ConnectionRefusedError):
        return "%s rechazó la conexión -> ¿servicio caído o puerto erróneo?" % host
    if isinstance(e, urllib.error.HTTPError):
        return "HTTP %s de %s -> revisa credenciales/token SSO" % (e.code, host)
    return str(e)


def _run(args, timeout=10):
    return subprocess.run(args, capture_output=True, timeout=timeout).stdout.decode(
        "utf-8", "replace"
    )


def run_doctor(cfg, ios_client=None):
    """Preflight completo del entorno iOS. Imprime [OK]/[WARN]/[FAIL] y
    devuelve el numero de fallos (0 = entorno listo)."""
    fails = [0]
    warns = [0]

    def ok(m):
        print("  [OK]   %s" % m)

    def warn(m):
        warns[0] += 1
        print("  [WARN] %s" % m)

    def fail(m):
        fails[0] += 1
        print("  [FAIL] %s" % m)

    print("=== Doctor VoiceOver Audit v%s ===\n" % VERSION)

    print("Anfitrión (macOS requerido)")
    if sys.platform == "darwin":
        ok("SO: macOS")
    else:
        fail(
            "SO %s -> voiceover_audit requiere macOS (iOS Simulator solo existe en macOS)"
            % sys.platform
        )

    vi = sys.version_info
    if vi >= (3, 9):
        ok("Python %d.%d.%d" % vi[:3])
    else:
        fail("Python %d.%d -> requiere >= 3.9" % vi[:2])

    swiftc_ok = False
    try:
        subprocess.run(["xcrun", "-f", "swiftc"], capture_output=True, check=True, timeout=10)
        ok("swiftc disponible (Xcode CLT)")
        swiftc_ok = True
    except Exception:
        fail("swiftc no disponible -> instala Command Line Tools: xcode-select --install")

    bridge = os.path.join(SCRIPT_DIR, "vo_bridge")
    if os.path.exists(bridge):
        ok("vo_bridge compilado")
    elif swiftc_ok:
        ok("vo_bridge pendiente de compilar (se compilará solo en la 1ª corrida)")
    else:
        fail("vo_bridge sin compilar y sin swiftc")

    ocr = os.path.join(SCRIPT_DIR, "vo_ocr")
    if os.path.exists(ocr):
        ok("vo_ocr compilado")
    elif swiftc_ok:
        ok("vo_ocr pendiente de compilar (se compilará solo)")
    else:
        warn("vo_ocr sin compilar y sin swiftc -> modo degradado")

    print("\nSimulador iOS")
    booted = []
    try:
        out = _run(["xcrun", "simctl", "list", "devices", "available"], timeout=15)
        for ln in out.splitlines():
            if "(Booted)" in ln:
                name = ln.split("(")[0].strip()
                booted.append(name)
        ok("xcrun simctl responde")
    except FileNotFoundError:
        fail("xcrun no encontrado -> instala Xcode + Command Line Tools")
    except Exception as e:
        fail("xcrun simctl falló: %s" % e)

    if not booted:
        warn("ningún simulador booteado -> arranca uno en Xcode/Simulator.app")
    else:
        ok("simulador activo: %s" % ", ".join(booted))
        app_pkg = (cfg.get("app_pkg") or "").strip()
        if app_pkg:
            try:
                _run(
                    ["xcrun", "simctl", "get_app_container", "booted", app_pkg, "app"],
                    timeout=15,
                )
                ok("app instalada: %s" % app_pkg)
            except Exception:
                fail(
                    "app %s NO instalada en el simulador -> instala con: --ipa <archivo>"
                    % app_pkg
                )
        else:
            warn("sin 'app_pkg' en el perfil -> no se puede verificar la app")

    print("\nRed / endpoints del perfil")
    eps = [
        (k, cfg.get(k))
        for k in ("login_url", "sso_url", "hybrid_cdn_url")
        if cfg.get(k)
    ]
    if not eps:
        warn("el perfil no define login_url/sso_url/hybrid_cdn_url (sin SSO/CDN)")
    for key, url in eps:
        okp, det = probe_host(url)
        host = urlparse(url).hostname or url
        if okp:
            ok("%s (%s): conecta" % (host, key))
        else:
            fail("%s (%s): %s -> %s" % (host, key, det, net_hint(url)))

    if cfg.get("login_url") and not (
        cfg.get("sso_url") and cfg.get("sso_body")
    ):
        warn("login_url definido pero falta sso_url/sso_body -> --login fallará")

    print("\nResultado: %d fallo(s), %d aviso(s)" % (fails[0], warns[0]))
    return fails[0]


_PUPPETEER_CHECK_JS = r"""
const path = require('path');
const cands = [
  path.join(process.env.HOME || '', '.npm-global/lib/node_modules/pa11y/node_modules/puppeteer'),
  '/usr/local/lib/node_modules/pa11y/node_modules/puppeteer',
  path.join(process.env.APPDATA || '', 'npm/node_modules/pa11y/node_modules/puppeteer'),
  path.join(process.env.APPDATA || '', 'npm/node_modules/puppeteer'),
  path.join(process.env.NPM_CONFIG_PREFIX || '', 'lib/node_modules/puppeteer'),
  'puppeteer'
];
for (const c of cands) {
  try { require(c); console.log('FOUND:' + c); process.exit(0); } catch (e) {}
}
console.log('MISS'); process.exit(1);
"""


def run_web_doctor(cfg):
    """Preflight completo del entorno macOS Web (VoiceOver + Chrome CDP).
    Devuelve el numero de fallos (0 = entorno listo)."""
    from .vo_mac import ax_is_trusted, screen_recording_ok
    from .web_client import find_chrome_binary

    fails = [0]
    warns = [0]

    def ok(m):
        print("  [OK]   %s" % m)

    def warn(m):
        warns[0] += 1
        print("  [WARN] %s" % m)

    def fail(m):
        fails[0] += 1
        print("  [FAIL] %s" % m)

    print("=== Doctor VoiceOver Web (macOS + Chrome) v%s ===\n" % VERSION)

    print("Anfitrión y permisos macOS (TCC)")
    if sys.platform == "darwin":
        ok("SO: macOS")
    else:
        fail("SO %s -> vo_web requiere macOS (VoiceOver de escritorio)" % sys.platform)

    vi = sys.version_info
    if vi >= (3, 9):
        ok("Python %d.%d.%d" % vi[:3])
    else:
        fail("Python %d.%d -> requiere >= 3.9" % vi[:2])

    if ax_is_trusted() and screen_recording_ok():
        ok("Permisos TCC (Accesibilidad + Grabación): concedidos (modo os-vo disponible)")
    else:
        ok("Modo CDP VoiceOver activo: no requiere permisos TCC de administrador (usa page.screenshot + AX/DOM de Chrome)")

    print("\nNavegador y CDP")
    node_ok = False
    try:
        v = subprocess.run(["node", "--version"], capture_output=True, text=True, timeout=10)
        ok("Node.js %s" % v.stdout.strip())
        node_ok = True
    except Exception:
        fail("node no encontrado en PATH -> instala Node.js 18+")

    if node_ok:
        r = subprocess.run(["node", "-e", _PUPPETEER_CHECK_JS], capture_output=True, text=True, timeout=20)
        found = (r.stdout or "").strip()
        if found.startswith("FOUND:"):
            ok("puppeteer resoluble (%s)" % found[6:])
        else:
            fail("puppeteer no resoluble -> npm i -g puppeteer (o pa11y)")

    chrome = find_chrome_binary(cfg)
    if chrome:
        ok("Chrome: %s" % chrome)
    else:
        warn("Chrome no encontrado en /Applications -> puppeteer usará Chrome for Testing si está instalado")

    print("\nRed / endpoints del perfil")
    eps = [(k, cfg.get(k)) for k in ("login_url", "target_url", "hybrid_cdn_url") if cfg.get(k)]
    if not eps:
        warn("el perfil no define login_url/target_url")
    for key, url in eps:
        okp, det = probe_host(url)
        host = urlparse(url).hostname or url
        if okp:
            ok("%s (%s): conecta" % (host, key))
        else:
            fail("%s (%s): %s -> %s" % (host, key, det, net_hint(url)))

    print("\nResultado: %d fallo(s), %d aviso(s)" % (fails[0], warns[0]))
    return fails[0]

"""Autenticacion SSO opcional pre-prueba y renovacion automatica en background para iOS."""

import json
import threading
import time
import urllib.request


def _post(url, body, headers=None):
    h = {"content-type": "application/json"}
    h.update(headers or {})
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(), headers=h, method="POST"
    )
    return urllib.request.urlopen(req, timeout=20).read()


def refresh_session(cfg, quiet=False):
    """Ejecuta los 2 POSTs de autenticacion (login + SSO) para refrescar la sesion en backend."""
    access = json.loads(_post(cfg["login_url"], cfg["login_body"]))["accessToken"]
    _post(cfg["sso_url"], cfg["sso_body"], {"accesstoken": access})
    if not quiet:
        u = cfg["sso_body"].get("username", "?")
        c = cfg["sso_body"].get("coreUserId", "?")
        print("      sesión SSO refrescada (username=%s, coreUserId=%s)" % (u, c))


def start_keep_alive(cfg, interval_sec):
    """Hilo daemon que renueva la sesion SSO cada interval_sec segundos."""
    stop_evt = threading.Event()

    def _worker():
        while not stop_evt.wait(interval_sec):
            try:
                refresh_session(cfg, quiet=True)
                print("      [keep-alive] sesión SSO renovada en background")
            except Exception as e:
                print("      [keep-alive] aviso: falló refresh (%s)" % e)

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    return stop_evt


def login_flow(ios_client, cfg):
    """Registra la sesion SSO en backend y relanza la aplicacion iOS."""
    app_pkg = cfg.get("app_pkg") or ""
    refresh_session(cfg, quiet=True)
    print("      sesión SSO registrada en backend; relanzando app iOS...")
    if app_pkg:
        ios_client.ensure_app_foreground(app_pkg, relaunch=True)
        time.sleep(2.5)

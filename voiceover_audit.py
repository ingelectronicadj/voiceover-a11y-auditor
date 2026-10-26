#!/usr/bin/env python3
"""
voiceover_audit.py - CLI principal de auditoria lineal de accesibilidad con iOS VoiceOver y Xcode.

Arquitectura modular en vo_audit/:
  - vo_audit.config       : configuracion centralizada (env vars / perfiles JSON)
  - vo_audit.ios_client   : cliente xcrun simctl, parcheo automatico de .ipa para Apple Silicon y puente AXAudit
  - vo_audit.rwi          : inspector WKWebView DOM / ARIA e IndexedDB via Safari Remote Web Inspector
  - vo_audit.sso          : autenticacion SSO opcional y keep-alive en segundo plano
  - vo_audit.vision       : OCR Vision (vo_ocr.swift) y deteccion de recuadro de foco
  - vo_audit.wcag_catalog : taxonomia oficial WCAG 2.2 (86 criterios) y catalogo de 16 reglas VO-*
  - vo_audit.rules        : motor de heuristicas sobre nodos, textos, skeletons, encabezados y omitidos
  - vo_audit.report       : persistencia steps.json, generador de report.html e index.html / ZIP
"""

import argparse
import datetime
import os
import re
import tempfile
import time

from vo_audit import VERSION
from vo_audit.config import LOCAL_CONFIG_PATH, load_config
from vo_audit.ios_client import IosClient
from vo_audit.report import build_report, build_suite_index, rebuild_report
from vo_audit.rules import is_a11y_relevant, text_a11y_issues
from vo_audit.rwi import capture_webview_dom, match_dom_element, run_rwi_steps
from vo_audit.sso import login_flow, refresh_session as _refresh_session, start_keep_alive
from vo_audit.vision import effective_label, ensure_ocr_binary
from vo_audit.wcag_catalog import WCAG_CATALOG, WCAG_CRITERIA, WCAG_ORDER, resolve_wcag_meta


def refresh_session(cfg=None, quiet=False, user_id=None, core_user_id=None):
    """Compatibilidad directa para invocaciones rapidas por CLI."""
    return _refresh_session(
        cfg or load_config(user_id=user_id, core_user_id=core_user_id),
        quiet=quiet,
    )


def run_self_test():
    """Autocomprobacion rapida sin simulador: valida catalogo WCAG 2.2, reglas VO-* y generador HTML."""
    assert len(WCAG_CRITERIA) == 86, "Se esperaban 86 criterios WCAG 2.2"
    for rk in WCAG_ORDER:
        cat = WCAG_CATALOG[rk]
        meta = resolve_wcag_meta(cat["criterion"])
        assert meta["level"] in ("A", "AA", "AAA")
        assert meta["w3c_url"].startswith("https://www.w3.org/WAI/WCAG22/Understanding/")
    assert any("Moneda" in x for x in text_a11y_issues("$ 11.415.305,40"))
    assert not any("Moneda" in x for x in text_a11y_issues("US$ 82.119,30"))
    assert any("Tropicalización" in x for x in text_a11y_issues("i18n_login_welcome_primary_button, Button"))
    sample_steps = [
        {
            "i": 1, "png": "img/step_001.png", "node": None,
            "utterance": "Siguiente", "raw_caption": "Siguiente",
            "page_title": "Transferencias", "is_skeleton": False,
            "box": (100, 200, 300, 260), "in_overlay": False, "label": "Siguiente",
            "screen_change": False,
        },
        {
            "i": 2, "png": "img/step_002.png", "node": None,
            "utterance": "", "raw_caption": "",
            "page_title": "Elegí con qué cuenta querés operar",
            "is_skeleton": True, "box": None, "in_overlay": False, "label": "",
            "screen_change": True,
        },
        {
            "i": 3, "png": "img/step_003.png", "node": None,
            "utterance": "i18n_login_welcome_primary_button, Button",
            "raw_caption": "i18n_login_welcome_primary_button, Button",
            "page_title": "Transferencias", "is_skeleton": False,
            "box": None, "in_overlay": False, "label": "i18n_login_welcome_primary_button",
            "screen_change": True,
        },
    ]
    with tempfile.TemporaryDirectory() as tmpdir:
        os.makedirs(os.path.join(tmpdir, "img"), exist_ok=True)
        out_html = build_report(sample_steps, [], set(), tmpdir, "self-test")
        content = open(out_html, encoding="utf-8").read()
        assert "VO-SKEL-001" in content, "Falta detección VO-SKEL-001 en self-test"
        assert "VO-FOCUS-001" in content, "Falta detección VO-FOCUS-001 en self-test"
        assert "VO-I18N-001" in content, "Falta detección VO-I18N-001 en self-test"
    print("Self-test OK (v%s): 86 criterios WCAG 2.2, %d reglas VO-* y generador HTML verificados." % (
        VERSION, len(WCAG_CATALOG)
    ))


def navigate_to_view(ios_client, cfg, view_spec):
    """Navega declarativamente a una vista configurada en cfg['views'][view_id]."""
    print("      [view] preparando vista '%s'..." % view_spec.get("title", "?"))
    if cfg.get("sso_url") and cfg.get("login_url"):
        try:
            _refresh_session(cfg)
        except Exception as e:
            print("      [view] aviso refresh SSO: %s" % e)
    pkg = cfg.get("app_pkg") or ""
    if pkg and view_spec.get("relaunch"):
        ios_client.ensure_app_foreground(pkg, relaunch=True)
    tap_match = view_spec.get("entry_match")
    tap_coord = view_spec.get("entry_norm_coord")
    if tap_match or tap_coord:
        ios_client.tap_accessible_element(match_text=tap_match, norm_coord=tap_coord)
        time.sleep(float(view_spec.get("entry_wait_sec", 6.0)))
    rwi_steps = view_spec.get("rwi_steps") or view_spec.get("cdp_steps")
    return capture_webview_dom(ios_client, cdp_steps=rwi_steps)


def _print_simulators(ios_client):
    sims = ios_client.list_simulators()
    print("Simuladores iOS disponibles en Xcode (%d):" % len(sims))
    for idx, s in enumerate(sims, 1):
        st = " [BOOTED]" if s["state"] == "Booted" else ""
        print("  %2d. %-28s | iOS %-6s | %s%s" % (idx, s["name"], s["ios_version"], s["udid"], st))
    return sims


def _print_installed_apps(ios_client):
    fg_pkg, _ = ios_client.get_foreground_package()
    apps = ios_client.list_installed_apps()
    print("Apps de usuario instaladas en %s (%s) (%d):" % (ios_client.device_name or ios_client.device, ios_client.os_version, len(apps)))
    for idx, p in enumerate(apps, 1):
        tag = "  [ACTIVA]" if p == fg_pkg else ""
        print("  %2d. %s%s" % (idx, p, tag))
    return apps, fg_pkg


def _slugify_device(name, ios_ver=""):
    s = re.sub(r"[^a-z0-9]+", "_", (name or "sim").lower().replace("xʀ", "xr")).strip("_")
    v = re.sub(r"[^0-9]+", "_", (ios_ver or "").lower()).strip("_")
    return ("%s_ios%s" % (s, v)) if v else s


def main():
    ap = argparse.ArgumentParser(description="Auditoría iOS VoiceOver con reporte visual (v%s)" % VERSION)
    ap.add_argument("--version", action="version", version="voiceover_audit %s" % VERSION)
    ap.add_argument("--profile", "-p", metavar="NAME", help="nombre del perfil en profiles/<NAME>.local.json")
    ap.add_argument("--config", metavar="FILE", help="archivo JSON de configuración opcional")
    ap.add_argument("--self-test", action="store_true", help="ejecuta autovalidación interna sin simulador y sale")
    ap.add_argument("--list-sims", action="store_true", help="lista todos los simuladores iOS disponibles en Xcode y sale")
    ap.add_argument("--list-apps", action="store_true", help="lista las apps instaladas en el simulador activo y sale")
    ap.add_argument("--ipa", metavar="IPA_OR_APP", help="instala un archivo .ipa (adaptándolo a Simulator en Apple Silicon) o .app en el simulador")
    ap.add_argument("--view", metavar="VIEW_ID", help="ID de vista declarada en config['views'] (o 'all' para ejecutar todas)")
    ap.add_argument("--view-title", metavar="TITLE", help="título descriptivo de la vista para la cabecera y pestaña del reporte")
    ap.add_argument("--steps", type=int, default=None, help="máx. de avances de foco (default 60 o según --view)")
    ap.add_argument("--backward", action="store_true", help="navegar hacia atrás en el orden de VoiceOver")
    ap.add_argument("--out", default=None, help="directorio del reporte")
    ap.add_argument("--pkg", default=None, metavar="BUNDLE_ID", help="bundleIdentifier iOS de la app bajo prueba")
    ap.add_argument("--locale", default=None, metavar="BCP47", help="idioma objetivo para el simulador iOS (ej. es-AR, en-US)")
    ap.add_argument("--device", default=None, help="UDID o nombre del simulador iOS (ej. 'iPhone 18 Pro', 'iPhone XR', 'booted')")
    ap.add_argument(
        "--devices",
        default=None,
        metavar="SIM_LIST",
        help="lista de simuladores separados por coma para pruebas comparativas multi-dispositivo/viewport (ej. 'iPhone 18 Pro,iPhone XR')",
    )
    ap.add_argument("--delay", type=float, default=0.75, help="espera tras cada avance de foco (s)")
    ap.add_argument("--no-ocr", action="store_true")
    ap.add_argument("--user", "-u", default=None, metavar="USER_ID", help="username y coreUserId para autenticación SSO opcional")
    ap.add_argument("--core-user-id", default=None, metavar="CORE_ID", help="coreUserId si difiere de --user")
    ap.add_argument("--login", action="store_true", help="ejecuta login SSO pre-auditoría")
    ap.add_argument("--refresh", action="store_true", help="refresca la sesión SSO (2 POSTs) antes de auditar")
    ap.add_argument("--keep-alive", type=float, default=None, metavar="SECS", help="renueva la sesión SSO en background cada N segundos")
    ap.add_argument("--test-modals", action="store_true", help="abre y cierra modales detectados para validar Focus Return (VO-FOCUS-001)")
    ap.add_argument("--pack", nargs="?", const="auto", default=None, metavar="ZIP_FILE", help="genera index.html maestro y empaqueta la suite en .zip")
    ap.add_argument("--rebuild", metavar="DIR", help="regenera report.html de una corrida previa")
    args = ap.parse_args()

    if args.self_test:
        run_self_test()
        return

    cfg = load_config(
        args.config,
        user_id=args.user,
        core_user_id=args.core_user_id,
        app_pkg=args.pkg,
        profile=args.profile,
    )

    if args.rebuild:
        print("Regenerando reporte desde %s ..." % args.rebuild)
        ocr_bin = None if args.no_ocr else ensure_ocr_binary()
        v_info = {"title": args.view_title} if args.view_title else None
        print("Reporte: %s" % rebuild_report(ocr_bin, args.rebuild, view_info=v_info, cfg=cfg))
        return

    probe_client = IosClient(timeout=cfg["sim_timeout"])
    if args.list_sims:
        _print_simulators(probe_client)
        return

    if args.devices:
        device_targets = [d.strip() for d in args.devices.split(",") if d.strip()]
    elif args.device:
        device_targets = [args.device]
    elif cfg.get("device_matrix"):
        device_targets = list(cfg["device_matrix"])
    else:
        device_targets = [cfg.get("device") or "booted"]

    views_cfg = cfg.get("views") or {}
    if args.view and args.view.lower() == "all":
        view_queue = list(views_cfg.keys())
    elif args.view:
        if args.view not in views_cfg:
            raise SystemExit(
                "Vista '%s' no encontrada en config['views'] (disponibles: %s)"
                % (args.view, ", ".join(views_cfg.keys()) or "ninguna")
            )
        view_queue = [args.view]
    else:
        view_queue = [None]

    ensure_ocr_binary()
    completed_dirs = []

    for dev_target in device_targets:
        ios_client = IosClient(device=dev_target, timeout=cfg["sim_timeout"])
        ios_client.ensure_simulator_running(dev_target)
        target_loc = args.locale or cfg.get("locale") or ""
        if target_loc:
            ios_client.ensure_locale(target_loc)
        env_info = ios_client.preflight_check()
        print("\n=== Dispositivo activo: %s (%s · UDID %s · locale %s) ===" % (
            env_info["name"], env_info["sdk"], env_info["device"], env_info["locale"]
        ))

        if args.list_apps:
            _print_installed_apps(ios_client)
            continue

        if args.ipa:
            installed_pkg = ios_client.install_app_or_ipa(args.ipa)
            if installed_pkg:
                cfg["app_pkg"] = installed_pkg
                ios_client.ensure_app_foreground(installed_pkg)

        if not cfg.get("app_pkg"):
            fg_pkg, _ = ios_client.get_foreground_package()
            if fg_pkg:
                cfg["app_pkg"] = fg_pkg
                print("      [auto-pkg] detectada app en el simulador: %s" % fg_pkg)

        if args.refresh:
            print("[0/3] Refrescando sesión SSO...")
            try:
                _refresh_session(cfg)
            except Exception as e:
                print("      ERROR refresh: %s" % e)

        if args.login:
            print("[0/3] Login SSO...")
            try:
                login_flow(ios_client, cfg)
            except Exception as e:
                print("      ERROR en login: %s" % e)
        elif cfg.get("app_pkg") and not args.ipa:
            ios_client.ensure_app_foreground(cfg["app_pkg"])

        dev_slug = _slugify_device(env_info["name"], ios_client.os_version)

        for v_id in view_queue:
            v_spec = views_cfg.get(v_id, {}) if v_id else {}
            base_out = (
                args.out
                if (args.out and len(view_queue) == 1)
                else v_spec.get("out")
                or os.path.join(
                    os.getcwd(),
                    "reportes",
                    "adhoc",
                    "voiceover_report_%s" % datetime.datetime.now().strftime("%Y%m%d_%H%M%S"),
                )
            )
            if len(device_targets) > 1:
                for stale_fn in ("report.html", "steps.json"):
                    stale_p = os.path.join(base_out, stale_fn)
                    if os.path.exists(stale_p):
                        try:
                            os.remove(stale_p)
                        except OSError:
                            pass
            cur_out = os.path.join(base_out, dev_slug) if len(device_targets) > 1 else base_out
            img_dir = os.path.join(cur_out, "img")
            os.makedirs(img_dir, exist_ok=True)
            for old_png in os.listdir(img_dir):
                if old_png.startswith("step_") and old_png.endswith(".png"):
                    try:
                        os.remove(os.path.join(img_dir, old_png))
                    except OSError:
                        pass

            max_steps = int(args.steps or v_spec.get("steps") or 60)
            if v_spec:
                dom_snapshot = navigate_to_view(ios_client, cfg, v_spec)
            else:
                dom_snapshot = capture_webview_dom(ios_client)
            if dom_snapshot:
                po_info = dom_snapshot.get("i18nDict") or {}
                po_str = (
                    ", i18n=%s (%s, %d keys)"
                    % (po_info.get("version", "?"), po_info.get("language", "?"), po_info.get("totalKeys", 0))
                    if po_info
                    else ""
                )
                print(
                    "      [RWI WKWebView] DOM capturado (%d elementos, %d puntos SVG, bundle=%s%s, url=%s)"
                    % (
                        len(dom_snapshot.get("elements", [])),
                        dom_snapshot.get("circleCount", 0),
                        dom_snapshot.get("bundleVersion") or "n/d",
                        po_str,
                        dom_snapshot.get("url", "").split("#")[-1],
                    )
                )

            ka_interval = cfg["keep_alive_sec"] if args.keep_alive is None else args.keep_alive
            ka_stop = start_keep_alive(cfg, ka_interval) if ka_interval and ka_interval > 0 else None
            try:
                print("[1/2] Ejecutando barrido lineal de VoiceOver en %s (%s)..." % (env_info["name"], env_info["sdk"]))
                steps, tree_nodes, visited = ios_client.run_bridge_walk(
                    cur_out,
                    max_steps=max_steps,
                    delay=args.delay,
                    backward=args.backward,
                    test_modals=args.test_modals,
                )
            finally:
                if ka_stop:
                    ka_stop.set()
                ios_client.reset_overlay()

            for s in steps:
                if dom_snapshot and not s.get("dom"):
                    s["dom"] = match_dom_element(s.get("utterance"), s.get("label"), dom_snapshot)
                if not s.get("label"):
                    n = s.get("node")
                    s["label"] = (effective_label(n, tree_nodes) if n else "") or (
                        s["dom"].get("label", "") if s.get("dom") else ""
                    )

            print("[2/2] Generando reporte HTML...")
            pkg = cfg.get("app_pkg") or "n/d"
            sso_user = (cfg.get("sso_body") or {}).get("username") or "n/d"
            extra_ver = ""
            if dom_snapshot:
                if dom_snapshot.get("bundleVersion"):
                    extra_ver += " · bundle=v%s" % dom_snapshot["bundleVersion"]
                po = dom_snapshot.get("i18nDict") or {}
                if po.get("version"):
                    db_lbl = po.get("dbName") or "i18n"
                    extra_ver += " · i18n=%s v%s (%s, %d keys)" % (
                        db_lbl,
                        po["version"],
                        po.get("language", ""),
                        po.get("totalKeys", 0),
                    )
            meta = "dispositivo=%s (%s, locale %s) · user=%s · bundleId=%s%s · modo=axaudit%s · pasos=%d · %s" % (
                env_info["name"],
                env_info["sdk"],
                env_info["locale"],
                sso_user,
                pkg,
                extra_ver,
                " atrás" if args.backward else "",
                len(steps),
                datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
            )
            base_title = args.view_title or v_spec.get("title") or "Vista iOS"
            if len(device_targets) > 1:
                full_title = "%s - %s (%s)" % (base_title, env_info["name"], env_info["sdk"])
            else:
                full_title = base_title
            view_info = {
                "title": full_title,
                "short_title": v_spec.get("short_title") or full_title,
                "scope_tag": v_spec.get("scope_tag"),
            }
            tree = [n for n in tree_nodes if is_a11y_relevant(n)]
            path = build_report(
                steps, tree, visited, cur_out, meta, dom_snapshot=dom_snapshot, view_info=view_info, cfg=cfg
            )
            completed_dirs.append(cur_out)
            print("Reporte: %s" % path)

    if len(completed_dirs) > 1 or args.pack:
        suite_dirs = completed_dirs
        if len(suite_dirs) <= 1 and views_cfg:
            suite_dirs = [
                v.get("out")
                for v in views_cfg.values()
                if v.get("out") and os.path.exists(os.path.join(v["out"], "report.html"))
            ] or completed_dirs
        zip_target = None
        if args.pack:
            zip_target = (
                os.path.join("reportes", "reportes_voiceover_suite_v%s.zip" % VERSION)
                if args.pack == "auto"
                else args.pack
            )
        suite_root = os.path.join("reportes", "app_staging") if any("app_staging" in d for d in suite_dirs) else None
        idx_p, zip_p = build_suite_index(
            suite_dirs,
            suite_dir=suite_root,
            zip_path=zip_target,
            suite_title="Suite de auditoría VoiceOver v%s (%d reportes)" % (VERSION, len(suite_dirs)),
        )
        if idx_p:
            print("Portada maestra: %s" % idx_p)
        if zip_p:
            print("Paquete ZIP:     %s" % zip_p)


if __name__ == "__main__":
    main()

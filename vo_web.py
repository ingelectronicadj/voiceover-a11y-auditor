#!/usr/bin/env python3
"""
vo_web.py - Auditoria lineal de accesibilidad Web con VoiceOver de macOS y Google Chrome.

Equivalente a nvda_audit (NVDA + Chrome en Windows/desktop) pero usando el VoiceOver
del sistema operativo: lanza Chrome visible, ejecuta login y navegacion declarativa
(`cdp_steps`), aplica las sondas dinamicas (`loading_probe`, `probe_control`) y despues
recorre la vista con el cursor de VoiceOver (VO+flecha), leyendo el panel de caption del
sistema (sin OCR) y capturando la ventana con el recuadro de foco.

Flujo por vista:
  1. Chrome CDP: login -> cdp_steps -> sondas DOM (loading_probe/probe_control)
  2. Sondeo del panel de caption de VoiceOver DURANTE la carga (anuncios live regions)
  3. Barrido lineal VO+Right: caption + screenshot de ventana por parada
  4. steps.json + announcements.json + report.html (mismo formato que voiceover_audit iOS)

Requisitos macOS: permisos de Accesibilidad y Grabacion de Pantalla para el proceso
lanzador; VoiceOver se activa/desactiva con Cmd+F5 (estado previo restaurado al salir,
salvo --keep-vo).
"""

import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time

from vo_audit import VERSION
from vo_audit.config import load_config
from vo_audit.doctor import run_web_doctor
from vo_audit.report import build_report, save_steps_json
from vo_audit.rwi import match_dom_element
from vo_audit.vo_mac import (
    ax_is_trusted,
    bring_app_front,
    capture_window,
    poll_captions,
    tcc_preflight,
    vo_caption,
    vo_is_running,
    vo_move_cursor,
    vo_set_enabled,
)
from vo_audit.web_client import WebClient


def run_self_test():
    """Autovalidacion sin navegador ni VoiceOver: modulos, runner JS y pipeline de reporte."""
    import ast
    import tempfile
    from vo_audit.web_client import VO_WEB_RUNNER_JS

    # 1. Sintaxis Python de los modulos nuevos
    for mod in ("vo_audit/vo_mac.py", "vo_audit/web_client.py", "vo_web.py"):
        src = open(os.path.join(os.path.dirname(__file__), mod), encoding="utf-8").read()
        ast.parse(src, filename=mod)

    # 2. Sintaxis del runner JS embebido (node --check si esta disponible)
    node = None
    for cand in ("node",):
        from shutil import which
        node = which(cand)
        if node:
            break
    if node:
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
            f.write(VO_WEB_RUNNER_JS)
            tmp_js = f.name
        rc = subprocess.run([node, "--check", tmp_js], capture_output=True).returncode
        assert rc == 0, "VO_WEB_RUNNER_JS no pasa node --check"
        os.remove(tmp_js)
        print("      runner JS: sintaxis OK (node --check)")
    else:
        print("      runner JS: node no disponible, se omite --check")

    # 3. Pipeline de reporte con pasos simulados + announcements
    with tempfile.TemporaryDirectory() as td:
        os.makedirs(os.path.join(td, "img"), exist_ok=True)
        open(os.path.join(td, "img", "step_001.png"), "wb").write(b"\x89PNG")
        steps = [{
            "i": 1, "png": os.path.join(td, "img", "step_001.png"), "node": None, "dom": None,
            "utterance": "Loading demo page, status", "raw_caption": "Loading demo page, status",
            "page_title": "Demo", "is_skeleton": False, "box": None,
            "in_overlay": False, "label": "Loading demo page", "screen_change": False,
        }]
        probes = [{
            "type": "loading_probe", "network": "Slow 3G", "skeleton_detected": True,
            "loading_announced": False, "screenshots": ["step_001.png"],
            "announcements": [{"selector": "screen-reader", "text": "\u200b", "codepoints": ["U+200B"]}],
            "vo_captions": [], "vo_spoken": False,
        }]
        save_steps_json(steps, [], set(), td, "vo_web self-test", probes=probes)
        path = build_report(steps, [], set(), td, "vo_web self-test", probes=probes)
        assert os.path.exists(path)
        html_out = open(path, encoding="utf-8").read()
        assert "sec-probes" in html_out, "Falta sec-probes en report.html de vo_web"
        assert "VO-STATUS-001" in html_out, "Falta VO-STATUS-001 desde loading_probe"
    print("Self-test OK (v%s): modulos vo_mac/web_client, runner JS y pipeline de reporte verificados." % VERSION)


def main():
    ap = argparse.ArgumentParser(description="Auditoria Web con VoiceOver macOS + Chrome (v%s)" % VERSION)
    ap.add_argument("--version", action="version", version="vo_web %s" % VERSION)
    ap.add_argument("--profile", "-p", metavar="NAME", help="perfil en profiles/<NAME>.local.json")
    ap.add_argument("--config", metavar="FILE", help="archivo JSON de configuracion opcional")
    ap.add_argument("--self-test", action="store_true", help="autovalidacion interna sin navegador ni VoiceOver")
    ap.add_argument("--doctor", action="store_true", help="verifica el entorno Web macOS (Python, Node, puppeteer, Chrome, permisos TCC, red) y sale")
    ap.add_argument("--view", metavar="VIEW_ID", help="ID de vista en config['web_views'] (o 'all')")
    ap.add_argument("--url", metavar="URL", help="URL adhoc a auditar (sin login ni cdp_steps)")
    ap.add_argument("--vo-steps", type=int, default=None, help="paradas del barrido VoiceOver (default 40 o segun vista)")
    ap.add_argument("--delay", type=float, default=0.9, help="espera tras cada VO+flecha (s)")
    ap.add_argument("--out", default=None, help="directorio del reporte")
    ap.add_argument("--nav-timeout", type=int, default=300, help="timeout de login+navegacion+sondas (s)")
    ap.add_argument("--keep-vo", action="store_true", help="no restaurar el estado previo de VoiceOver al terminar")
    ap.add_argument("--no-sweep", action="store_true", help="solo navegacion+sondas DOM, sin barrido VoiceOver")
    ap.add_argument("--no-clips", action="store_true", help="desactiva la generacion automatica de clips .mp4 cortos por hallazgo")
    ap.add_argument("--diff", nargs=2, metavar=("BEFORE_DIR", "AFTER_DIR"), help="compara dos corridas VoiceOver y genera diff_report.html + clip .mp4 lado a lado")
    args = ap.parse_args()

    if args.self_test:
        run_self_test()
        return

    if args.diff:
        from vo_audit.video import build_diff_report

        d_html, d_mp4 = build_diff_report(args.diff[0], args.diff[1], args.out)
        print("Reporte de regresion Before/After: %s" % d_html)
        if d_mp4:
            print("Clip comparativo Before/After:     %s" % d_mp4)
        return

    cfg = load_config(args.config, profile=args.profile)
    if args.doctor:
        print("Perfil activo: %s" % args.profile)
        raise SystemExit(run_web_doctor(cfg))
    web_views = cfg.get("web_views") or {}

    if args.url:
        view_queue = [None]
    elif args.view and args.view.lower() == "all":
        view_queue = list(web_views.keys())
    elif args.view:
        if args.view not in web_views:
            raise SystemExit(
                "Vista '%s' no encontrada en web_views (disponibles: %s)"
                % (args.view, ", ".join(web_views.keys()) or "ninguna")
            )
        view_queue = [args.view]
    else:
        if not web_views:
            raise SystemExit("Sin --url ni vistas en config['web_views'].")
        view_queue = [list(web_views.keys())[0]]

    # Si el Mac tiene permisos TCC (Accesibilidad + Grabacion de Pantalla), puede usar
    # System Events sobre VoiceOver.app; si estan bloqueados por MDM/admin corporativo,
    # ejecuta automaticamente el barrido lineal VoiceOver macOS via Chrome CDP (sin permisos de admin).
    missing_tcc = tcc_preflight()
    use_os_vo = (not args.no_sweep) and (len(missing_tcc) == 0)
    use_cdp_sweep = (not args.no_sweep) and (not use_os_vo)
    if use_cdp_sweep:
        print("[0/3] Sin permisos TCC de admin -> usando barrido VoiceOver macOS via Chrome CDP (no requiere permisos de sistema).")

    vo_was_on = vo_is_running() if use_os_vo else False
    if use_os_vo and not vo_was_on:
        print("[0/3] Activando VoiceOver...")
        if not vo_set_enabled(True):
            print("      [WARN] no se pudo activar VoiceOver; pasando a barrido CDP")
            use_os_vo = False
            use_cdp_sweep = True
    elif use_os_vo and vo_was_on:
        print("[0/3] VoiceOver ya esta activo.")

    client = WebClient(cfg)
    completed = []
    try:
        for v_id in view_queue:
            v_spec = web_views.get(v_id, {}) if v_id else {}
            out_dir = args.out or v_spec.get("out") or os.path.join(
                os.getcwd(), "reportes", "vo_web", "vo_web_%s" % datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            )
            img_dir = os.path.join(out_dir, "img")
            os.makedirs(img_dir, exist_ok=True)
            for old_png in os.listdir(img_dir):
                if old_png.startswith("step_") and old_png.endswith(".png"):
                    try:
                        os.remove(os.path.join(img_dir, old_png))
                    except OSError:
                        pass

            if args.url:
                cdp_steps = [{"goto_url": args.url, "wait_sec": 4.0}]
            else:
                cdp_steps = v_spec.get("cdp_steps") or []
            max_steps = int(args.vo_steps or v_spec.get("steps") or 40)
            view = {
                "id": v_id or "adhoc",
                "title": v_spec.get("title") or args.url or "Vista adhoc",
                "out_dir": out_dir,
                "max_steps": max_steps,
                "cdp_steps": cdp_steps,
            }

            print("[1/3] Chrome CDP: login + navegacion + sondas%s..." % (" + barrido VoiceOver" if use_cdp_sweep else ""))
            client.launch([view], cdp_sweep=use_cdp_sweep, keep_open=use_os_vo, headless=bool(cfg.get("headless", False)))

            announcements = []
            stop_poll = threading.Event()
            t = None
            if use_os_vo and ax_is_trusted():
                t = threading.Thread(target=poll_captions, args=(stop_poll.is_set, announcements), daemon=True)
                t.start()
            results = client.wait_ready(timeout=args.nav_timeout)
            stop_poll.set()
            if t:
                t.join(timeout=5)

            if results is None:
                print("      [ERROR] timeout esperando al runner de Chrome")
                break
            vres = (results or {}).get(view["id"]) or {}
            probes = vres.get("probes") or []
            dom_snapshot = vres.get("dom_snapshot")
            if isinstance(dom_snapshot, dict):
                dom_snapshot["vo_announcements"] = announcements
                dom_snapshot["final_announcers"] = vres.get("announcers")
            if use_os_vo and ax_is_trusted():
                vo_spoke_load = any(re.search(r"load|carg|esper|wait", c.get("text") or "", re.I) for c in announcements)
                for pr in probes:
                    if pr.get("type") == "loading_probe":
                        pr["vo_captions"] = announcements
                        pr["vo_spoken"] = vo_spoke_load
            print(
                "      vista lista: url=%s h1=%r announcers=%d probes=%d dom_els=%d"
                % (
                    vres.get("url") or "?",
                    vres.get("h1") or "",
                    len(vres.get("announcers") or []),
                    len(probes),
                    len((dom_snapshot or {}).get("elements") or []),
                )
            )
            if announcements:
                print("      anuncios capturados en caption durante la carga: %d" % len(announcements))
                for a in announcements[:10]:
                    print("        [t=%5.1fs] %s" % (a["t"], a["text"][:90]))

            steps = []
            tree_nodes = vres.get("tree_nodes") or []
            visited = {
                (k[0], k[1], k[2], tuple(k[3]) if k[3] else None)
                for k in (vres.get("visited") or [])
            }
            if use_cdp_sweep:
                for s in vres.get("steps") or []:
                    dom_el = match_dom_element(s.get("utterance"), s.get("label"), dom_snapshot, box=s.get("box")) if dom_snapshot else None
                    s["dom"] = dom_el
                    steps.append(s)
            elif use_os_vo:
                print("[2/3] Barrido VoiceOver (VO+Right x %d)..." % max_steps)
                bring_app_front("Google Chrome")
                time.sleep(1.0)
                prev_txt = ""
                for i in range(1, max_steps + 1):
                    vo_move_cursor()
                    time.sleep(args.delay)
                    txt = vo_caption()
                    png_rel = "img/step_%03d.png" % i
                    png_abs = os.path.join(out_dir, png_rel)
                    capture_window(png_abs)
                    dom_el = match_dom_element(txt, txt, dom_snapshot) if dom_snapshot else None
                    steps.append({
                        "i": i,
                        "png": png_abs,
                        "node": None,
                        "dom": dom_el,
                        "utterance": txt,
                        "raw_caption": txt,
                        "page_title": vres.get("h1") or "",
                        "is_skeleton": False,
                        "box": None,
                        "in_overlay": False,
                        "label": (dom_el.get("label") if dom_el else "") or txt,
                        "screen_change": False,
                    })
                    print("      %3d. %s" % (i, (txt or "(sin caption)")[:70]))
                    if txt and txt == prev_txt and i > 4:
                        print("      caption repetido; fin del contenido nuevo")
                        steps.pop()
                        break
                    prev_txt = txt
            elif probes or dom_snapshot:
                # En modo --no-sweep crear paso sintetico 1 para anclar hallazgos DOM/probes en report.html
                step1_png = os.path.join(out_dir, "img", "step_001.png")
                if not os.path.exists(step1_png):
                    for pr in probes:
                        shots = pr.get("screenshots") or []
                        if shots and os.path.exists(os.path.join(out_dir, "img", shots[0])):
                            shutil.copy2(os.path.join(out_dir, "img", shots[0]), step1_png)
                            break
                h1_lbl = (vres.get("h1") or view["title"] or "Vista Web").strip()
                steps.append({
                    "i": 1,
                    "png": step1_png,
                    "node": None,
                    "dom": match_dom_element(h1_lbl, h1_lbl, dom_snapshot) if dom_snapshot else None,
                    "utterance": "heading level 1, %s" % h1_lbl,
                    "raw_caption": "heading level 1, %s" % h1_lbl,
                    "page_title": h1_lbl,
                    "is_skeleton": False,
                    "box": None,
                    "in_overlay": False,
                    "label": h1_lbl,
                    "screen_change": False,
                })

            print("[3/3] Generando reporte...")
            meta = "plataforma=macOS VoiceOver + Chrome · modo=%s · url=%s · pasos=%d · %s" % (
                "cdp-vo" if use_cdp_sweep else ("os-vo" if use_os_vo else "no-sweep"),
                vres.get("url") or args.url or "?",
                len(steps),
                datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
            )
            view_info = {
                "title": view["title"],
                "short_title": v_spec.get("short_title") or view["title"],
                "scope_tag": v_spec.get("scope_tag") or "",
                "route_hash": (vres.get("url") or "").split("#")[-1],
            }
            save_steps_json(
                steps, tree_nodes, visited, out_dir, meta,
                dom_snapshot=dom_snapshot or {"vo_announcements": announcements, "final_announcers": vres.get("announcers")},
                view_info=view_info,
                probes=probes,
            )
            ann_path = os.path.join(out_dir, "announcements.json")
            with open(ann_path, "w", encoding="utf-8") as f:
                json.dump({"vo_captions": announcements, "probes": probes}, f, indent=2, ensure_ascii=False)
            path = build_report(
                steps,
                tree_nodes,
                visited,
                out_dir,
                meta,
                dom_snapshot=dom_snapshot,
                view_info=view_info,
                cfg=cfg,
                probes=probes,
                enable_clips=not getattr(args, "no_clips", False),
            )
            print("Reporte: %s" % path)
            completed.append(out_dir)
    finally:
        client.close()
        if use_os_vo and not args.keep_vo and not vo_was_on and vo_is_running():
            print("Restaurando estado: desactivando VoiceOver...")
            vo_set_enabled(False)


if __name__ == "__main__":
    main()

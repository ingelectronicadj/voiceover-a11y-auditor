"""Procesamiento visual de capturas de iOS Simulator y OCR con Vision.framework (vo_ocr.swift)."""

import os
import re
import subprocess
from .config import SCRIPT_DIR
from .rules import norm_utt


def _is_fullscreen_container(n):
    short = (n.get("cls") or "").split(".")[-1]
    if short in ("UIWindow", "UILayoutContainerView", "WKWebView", "WKContentView"):
        return True
    b = n.get("bounds")
    if b and (b[2] - b[0]) * (b[3] - b[1]) > 1800000:
        return True
    return False


def match_node(box, nodes, utterance=""):
    """Correlaciona el paso con su nodo accesible en nodes."""
    utt_n = norm_utt(utterance)
    if utt_n and len(utt_n) >= 2:
        candidates = []
        for n in nodes:
            if _is_fullscreen_container(n):
                continue
            lbl = (n.get("desc") or n.get("text") or "").strip()
            ln = norm_utt(lbl)
            if not ln:
                continue
            if ln == utt_n or (len(ln) >= 3 and ln in utt_n) or (len(utt_n) >= 4 and utt_n in ln):
                dist = 999999
                if box and n.get("bounds"):
                    bx, by = (box[0] + box[2]) // 2, (box[1] + box[3]) // 2
                    nx, ny = (n["bounds"][0] + n["bounds"][2]) // 2, (n["bounds"][1] + n["bounds"][3]) // 2
                    dist = abs(bx - nx) + abs(by - ny)
                candidates.append((min(len(ln), len(utt_n)), -dist, n))
        if candidates:
            candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
            return candidates[0][2]

    best_cover, best_center = None, None
    if box:
        bx1, by1, bx2, by2 = box
        barea = max(1, (bx2 - bx1) * (by2 - by1))
        cx, cy = (bx1 + bx2) // 2, (by1 + by2) // 2
        for n in nodes:
            if not n.get("bounds") or _is_fullscreen_container(n):
                continue
            x1, y1, x2, y2 = n["bounds"]
            area = (x2 - x1) * (y2 - y1)
            if area <= 0 or area > 1800000:
                continue
            iw = max(0, min(bx2, x2) - max(bx1, x1))
            ih = max(0, min(by2, y2) - max(by1, y1))
            inter = iw * ih
            if inter / barea > 0.55 and (best_cover is None or area < best_cover[0]):
                best_cover = (area, n)
            if x1 <= cx <= x2 and y1 <= cy <= y2 and (best_center is None or area < best_center[0]):
                best_center = (area, n)
    return (best_cover or best_center or (None, None))[1]


def effective_label(node, nodes):
    """Etiqueta efectiva del nodo enfocado."""
    if not node or _is_fullscreen_container(node):
        return ""
    label = (node.get("text") or node.get("desc") or "").strip()
    if label:
        return label
    if not node.get("bounds"):
        return ""
    x1, y1, x2, y2 = node["bounds"]
    if (x2 - x1) * (y2 - y1) > 900000:
        return ""
    inner = []
    for n in nodes:
        if not n.get("bounds") or n is node:
            continue
        nx1, ny1, nx2, ny2 = n["bounds"]
        if x1 <= nx1 and ny1 >= y1 and nx2 <= x2 and ny2 <= y2:
            t = (n.get("text") or n.get("desc") or "").strip()
            if t:
                inner.append((ny1, nx1, t))
    inner.sort()
    return " ".join(t for _, _, t in inner)[:180]


def ensure_ocr_binary():
    src = os.path.join(SCRIPT_DIR, "vo_ocr.swift")
    binpath = os.path.join(SCRIPT_DIR, "vo_ocr")
    if os.path.exists(binpath) and os.path.getmtime(binpath) >= os.path.getmtime(src):
        return binpath
    try:
        subprocess.run(
            ["swiftc", "-O", src, "-o", binpath],
            check=True,
            capture_output=True,
            timeout=120,
        )
        return binpath
    except Exception as e:
        print("OCR no disponible (%s); el reporte usará los metadatos de AXAudit." % e)
        return None


def ocr_step_info(ocr_bin, png_path, bar_y=None):
    """Analiza por OCR la captura del paso para extraer page_title, is_skeleton y box."""
    if not ocr_bin or not os.path.exists(png_path):
        return {"utterance": "", "raw_caption": "", "page_title": "", "is_skeleton": False, "box": None}
    try:
        out = subprocess.run(
            [ocr_bin, png_path], capture_output=True, text=True, timeout=60
        ).stdout
    except Exception:
        return {"utterance": "", "raw_caption": "", "page_title": "", "is_skeleton": False, "box": None}
    hdr_lines, body_lines = [], []
    box = None
    for ln in out.splitlines():
        if ln.startswith("BOX\t"):
            coords = ln.split("\t", 1)[1].split(",")
            if len(coords) == 4:
                box = [int(c) for c in coords]
            continue
        m = re.match(r"([\d.]+),([\d.]+),([\d.]+),([\d.]+)\t(.*)", ln)
        if not m:
            continue
        x, y, w, h, txt = (
            float(m[1]),
            float(m[2]),
            float(m[3]),
            float(m[4]),
            m[5].strip(),
        )
        cy = y + h / 2
        if 0.05 <= cy <= 0.185:
            if len(txt.strip(" <xX•·")) >= 3:
                hdr_lines.append((cy, x, txt))
        elif 0.185 < cy < 0.85:
            if len(txt.strip(" •·.,:")) >= 2:
                body_lines.append((cy, txt))
    hdr_lines.sort()
    page_title = " ".join(t for _, _, t in hdr_lines).strip()
    is_skeleton = bool(page_title and len(body_lines) == 0)
    return {
        "utterance": "",
        "raw_caption": "",
        "page_title": page_title,
        "is_skeleton": is_skeleton,
        "box": box,
    }

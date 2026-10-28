"""Motor de heuristicas de accesibilidad sobre nodos iOS / WKWebView, textos y secuencias de foco de VoiceOver."""

import re
from .config import CURRENCY_NOTES, INTERESTING_CLS, SKIP_CLS

EN_SPEECH_PATTERNS = (
    r",\s*button\b",
    r",\s*header\b",
    r",\s*heading\b",
    r",\s*link\b",
    r"\bdouble-tap to activate\b",
    r"\bdimmed\b",
    r"\bin list\b",
)

MODAL_PATTERNS = (
    r"eleg[ií] con qu[eé] cuenta",
    r"comisi[oó]n de compra,\s*es el coste",
    r"precio aproximado,\s*es el precio",
)


def norm_utt(u):
    """Forma canonica de una utterance para comparar pasos consecutivos."""
    if not u:
        return ""
    s = u.lower()
    s = re.sub(
        r"\b(double-tap to activate|pulsa dos veces para activar|toca dos veces para activar|tocá dos veces para activar)\b",
        "",
        s,
    )
    s = re.sub(r"(\d)[xłl]\b", r"\1", s)
    s = re.sub(r"[^a-záéíóúñü0-9$_]+", " ", s).strip()
    return s


def node_key(n):
    return (
        n.get("text", ""),
        n.get("desc", ""),
        n.get("cls", ""),
        tuple(n["bounds"]) if n.get("bounds") else None,
    )


def is_a11y_relevant(n):
    """Nodo que VoiceOver visitaria: tiene etiqueta o es un control interactivo real."""
    label = ((n.get("text") or "") + (n.get("desc") or "")).strip()
    if label:
        return True
    short = (n.get("cls") or "").split(".")[-1]
    if any(short.endswith(c) for c in SKIP_CLS):
        return False
    if n.get("clickable") or n.get("checked") == "true":
        return True
    return any(c.lower() in short.lower() for c in INTERESTING_CLS)


def text_a11y_issues(text, expected_locale="es"):
    """Heuristicas sobre cualquier texto/etiqueta o utterance anunciada por VoiceOver."""
    issues = []
    if not text:
        return issues
    exp_en = (expected_locale or "").lower().startswith("en")
    without_usd = re.sub(r"US\$\s*", "", text)
    if "$" in without_usd and not exp_en:
        issues.append(
            "Moneda (WCAG 1.3.1): el símbolo '$' sin desambiguar se sintetiza como 'dólares' en TTS español aunque represente pesos ARS"
        )
    for sym, note in CURRENCY_NOTES.items():
        if sym != "$" and sym != "€" and sym in text:
            issues.append("Moneda: " + note)
    m_dup_val = re.search(
        r"(?:available balance|saldo disponible|available titles|t[ií]tulos disponibles)\s+([€$£]?\s*\d+[.,]?\d*(?:\s+titles|\s+t[ií]tulos)?)\b.*\.\s*(?:\1|0\s+titles)\b",
        text.lower(),
    )
    if m_dup_val:
        issues.append(
            "Encabezados y etiquetas (WCAG 2.4.6 / 4.1.2): la etiqueta accesible repite al final un importe o unidad ya anunciado («%s»)"
            % text[:85]
        )
    words = text.split()
    if len(words) >= 18:
        issues.append(
            "Contenedor fusionado (WCAG 1.3.2): %d palabras en un único anuncio; dificulta navegar elementos por separado"
            % len(words)
        )
    low = text.lower()
    if not exp_en and any(re.search(p, low) for p in EN_SPEECH_PATTERNS):
        issues.append(
            "Idioma / Locale (WCAG 3.1.2): anuncio incluye traits del sistema en inglés («%s») con locale configurado en inglés"
            % text[-25:].strip(" ,·")
        )
    if re.search(r"tuvimos un problema|ocurri[oó] un error al cargar|no es posible recuperar|something went wrong|unable to retrieve", low):
        issues.append(
            "Mensajes de estado (WCAG 4.1.3): estado de error en pantalla («%s»)"
            % text[:70]
        )
    if low.strip() in ("status", "estado"):
        issues.append(
            "Mensajes de estado (WCAG 4.1.3): región viva role='status' anunciada vacía («%s») sin texto de carga asociado"
            % text.strip()
        )
    ph = re.findall(r"\{[A-Za-z0-9_.\s]{2,30}\}", text)
    if ph:
        issues.append(
            "Tropicalización / i18n (WCAG 3.1.2 / 2.4.6): variable o placeholder sin interpolar expuesto al lector (%s)"
            % ", ".join(ph[:3])
        )
    raw_keys = re.findall(r"\b(?:a11y|i18n|msg)_[a-z0-9_]{4,}\b|\b[a-z]{2,4}_[a-z]{2,4}_[a-z0-9_]{8,}\b", low)
    if raw_keys:
        issues.append(
            "Tropicalización / i18n (WCAG 3.1.2 / 4.1.2): key técnica cruda sin resolver expuesta en VoiceOver («%s»)"
            % ", ".join(raw_keys[:2])
        )
    elif not exp_en and re.search(
        r"associated account|available balance|you can change the associated account|"
        r"select your linked account|select an option|choose one account|"
        r"select the amount|change frequency|you can only select a",
        text.lower(),
    ):
        issues.append(
            "Tropicalización / i18n (WCAG 3.1.2): etiqueta accesible en inglés sin localizar en vista en español («%s»)"
            % text[:80]
        )
    elif exp_en and re.search(
        r"\b(en el complejo ecosistema|en el actual ecosistema|descripci[oó]n corta|pendiente del equipo|trading volumen)\b",
        text.lower(),
    ):
        issues.append(
            "Tropicalización / i18n (WCAG 3.1.2): texto o término en español sin traducir expuesto en vista en inglés («%s»)"
            % text[:80]
        )
    if re.search(r",\s*0\s*,\s*toggle\b", low):
        issues.append(
            "Nombre accesible (WCAG 4.1.2): píldora interactiva expone valor crudo '0, Toggle' y duplica la parada de foco respecto a su etiqueta de texto"
        )
    if re.search(r"\b[uú]ltimas\s+ordenes\b|\bultimas\s+[oó]rdenes\b", low):
        issues.append(
            "Tropicalización / i18n (WCAG 2.4.6): inconsistencia ortográfica en encabezado («%s» sin tilde)"
            % text[:50]
        )
    if re.search(r"\b(puedes cambiar|quieres comprar|tienes disponible|selecciona el|ingresa el)\b", low):
        issues.append(
            "Tropicalización / i18n (WCAG 3.1.2): texto en tuteo (es-ES) en lugar de voseo es-AR («%s»)"
            % text[:70]
        )
    if re.search(
        r"^\s*\(?(abrir una nueva ventana|open a new window)\)?[\s.·,]*(enlace|v[ií]nculo|link)?\s*$",
        text.lower(),
    ):
        issues.append(
            "Propósito de los enlaces (WCAG 2.4.4): enlace sin texto de destino; anuncia únicamente «%s»"
            % text[:60]
        )
    elif re.search(r"\b(saber m[aá]s[.\s·,]+saber m[aá]s|learn more[.\s·,]+learn more)\b", low):
        issues.append(
            "Propósito de los enlaces (WCAG 2.4.4): etiqueta accesible duplica el texto («Saber más / Learn more») en el anuncio del enlace"
        )
    if re.search(
        r"unlabelled|unlabeled|sin etiquetar|posible texto|possible text|detected:\s*text",
        text.lower(),
    ):
        issues.append(
            "Contenido no textual (WCAG 1.1.1): imagen o gráfico sin atributo alt/accessibilityLabel (VoiceOver anuncia 'Imagen sin etiquetar' o recurre a OCR)"
        )
    return issues


def node_issues(node, expected_locale="es"):
    issues = []
    text_vis = (node.get("text") or "").strip()
    desc = (node.get("desc") or "").strip()
    label = desc or text_vis
    cls_short = (node.get("cls") or "").split(".")[-1]
    native_cls = (node.get("native_cls") or "").split(".")[-1]
    rid = node.get("rid") or ""
    traits = [str(t).lower() for t in (node.get("traits") or [])]
    issues.extend(text_a11y_issues(label, expected_locale=expected_locale))
    if ("TextField" in native_cls or "TextField" in rid) and not traits:
        issues.append(
            "Nombre accesible (WCAG 4.1.2): campo de texto (%s) carece de rol/trait de edición en VoiceOver (anuncia solo «%s» sin indicar 'Campo de texto' / 'Text Field')"
            % (native_cls or rid, label[:40])
        )
    if ("Logo" in rid or "logo" in label.lower()) and "header" in traits:
        issues.append(
            "Jerarquía de encabezados (WCAG 1.3.1 / 2.4.6): logotipo gráfico («%s») marcado con trait 'Header' (Encabezado) en lugar de trait 'Image' (Imagen)"
            % label[:45]
        )
    if "Image" in cls_short and not label:
        issues.append(
            "Contenido no textual (WCAG 1.1.1): imagen o icono sin texto alternativo (accessibilityLabel)"
        )
    elif (
        (node.get("clickable") or node.get("focusable"))
        and not label
        and "TextField" not in cls_short
    ):
        issues.append(
            "Nombre accesible (WCAG 4.1.2): elemento interactivo sin etiqueta accesible (accessibilityLabel)"
        )
    if text_vis and desc and text_vis.lower() not in desc.lower():
        issues.append(
            "Etiqueta en el nombre (WCAG 2.5.3): accessibilityLabel («%s») no incluye el texto visible («%s»)"
            % (desc[:40], text_vis[:40])
        )
    if label and re.search(r"\b(bot[oó]n|button|icono|icon|imagen|image)\b", label.lower()):
        issues.append(
            "Encabezados y etiquetas (WCAG 2.4.6): la etiqueta incluye el nombre del rol («%s»), generando anuncio redundante con el trait de VoiceOver"
            % label[:40]
        )
    if node.get("clickable") and node.get("bounds"):
        x1, y1, x2, y2 = node["bounds"]
        if 0 < (x2 - x1) < 44 or 0 < (y2 - y1) < 44:
            issues.append(
                "Tamaño del objetivo (WCAG 2.5.8): área táctil de %dx%d px inferior al mínimo recomendado"
                % (x2 - x1, y2 - y1)
            )
    return issues


def analyze_sequence_issues(steps):
    """Analiza la secuencia completa de pasos de VoiceOver."""
    prev_norm = None
    in_modal = False
    pre_modal_norm = None
    pre_modal_step = None
    chart_streak = 0
    chart_flagged = False
    link_frag_streak = 0
    link_frag_flagged = False
    for s in steps:
        utt = s.get("utterance") or ""
        raw_cap = s.get("raw_caption") or ""
        lbl = s.get("label") or ""
        ptitle = s.get("page_title") or ""
        is_skel = bool(s.get("is_skeleton"))
        s["seq_issues"] = []
        s["is_loading_ann"] = bool(
            re.search(r"\b(cargando|loading)\b", (utt + " " + raw_cap).lower())
        )
        if re.search(r"(fecha:.*valor|date:.*value)", (utt + " " + lbl).lower()):
            chart_streak += 1
            if chart_streak == 5 and not chart_flagged:
                chart_flagged = True
                s["seq_issues"].append(
                    "Gráfica sin salto de bloque (WCAG 2.4.1): VoiceOver recorre punto por punto de la gráfica (%d+ nodos expuestos en el árbol AX), atrapando la navegación lineal"
                    % chart_streak
                )
        else:
            chart_streak = 0
            chart_flagged = False
        if re.search(r",\s*(link|enlace|v[ií]nculo)(\s*,\s*(image|imagen))?\s*$", utt.lower()):
            link_frag_streak += 1
            if link_frag_streak == 5 and not link_frag_flagged:
                link_frag_flagged = True
                s["seq_issues"].append(
                    "Contenedor fusionado (WCAG 1.3.2): en iOS WKWebView cada enlace compuesto <a> se fragmenta en 5 paradas separadas de VoiceOver (nombre, ticker, importe, icono tendencia, porcentaje) por falta de aria-label unificado"
                )
        else:
            link_frag_streak = 0
        if is_skel:
            s["in_overlay"] = False
            has_loading_ann = bool(
                re.search(r"\b(loading|cargando)\b", (utt + " " + raw_cap).lower())
            )
            if not has_loading_ann:
                actual_spoken = utt or raw_cap or "sin anuncio"
                s["seq_issues"].append(
                    "Estado de carga / Skeleton (WCAG 4.1.3 / 2.4.3): se presentan skeletons en «%s» "
                    "sin anunciar «Loading %s» / «Cargando %s» (solo se anunció «%s»)"
                    % (ptitle, ptitle, ptitle, actual_spoken)
                )
        elif not utt and not lbl and not s.get("node"):
            s["in_overlay"] = True
        nu = (
            ("skel:" + norm_utt(ptitle))
            if is_skel
            else (norm_utt(utt) or norm_utt(lbl))
        )
        s["is_duplicate"] = bool(
            nu
            and prev_norm
            and (
                nu == prev_norm
                or (len(nu) > 15 and (nu in prev_norm or prev_norm in nu))
            )
        )
        is_modal_now = bool(s.get("is_modal")) or any(
            re.search(p, (utt + " " + lbl + " " + ptitle).lower())
            for p in MODAL_PATTERNS
        )
        s["is_modal"] = is_modal_now
        if is_modal_now and not in_modal:
            in_modal = True
        elif not is_modal_now and in_modal and nu and not is_skel:
            in_modal = False
            if pre_modal_norm and nu != pre_modal_norm:
                s["seq_issues"].append(
                    "Gestión de foco / Focus Return (WCAG 2.4.3): al cerrar la modal/tooltip, "
                    "el foco de VoiceOver no regresó al disparador previo (paso #%s) sino a «%s»"
                    % (pre_modal_step, (utt or lbl)[:60])
                )
        if not is_modal_now and not is_skel and nu and not s.get("in_overlay"):
            pre_modal_norm = nu
            pre_modal_step = s["i"]
        if nu:
            prev_norm = nu

    # Detectar inversión de orden de foco horizontal (izquierda-derecha) en barras de acciones
    for idx in range(1, len(steps)):
        prev_s = steps[idx - 1]
        cur_s = steps[idx]
        b1 = prev_s.get("box")
        b2 = cur_s.get("box")
        if b1 and b2 and len(b1) == 4 and len(b2) == 4:
            cy1 = (b1[1] + b1[3]) / 2.0
            cy2 = (b2[1] + b2[3]) / 2.0
            # Si ambos controles están en la misma fila horizontal (ej. barra inferior) pero el foco va de derecha a izquierda
            if abs(cy1 - cy2) <= 45 and cy1 > 1600 and (b2[2] < b1[0] - 40):
                cur_s.setdefault("seq_issues", []).append(
                    "Gestión de foco / Focus Return (WCAG 2.4.3): orden de foco invertido respecto al layout visual (enfoca primero «%s» a la derecha y luego «%s» a la izquierda)"
                    % ((prev_s.get("label") or prev_s.get("utterance") or "")[:35], (cur_s.get("label") or cur_s.get("utterance") or "")[:35])
                )


def analyze_heading_hierarchy(dom_snapshot, steps):
    """Extrae el mapa jerarquico de encabezados (H1-H6 / trait Header) y detecta saltos de nivel."""
    headings = []
    issues = []
    els = (dom_snapshot or {}).get("elements") if isinstance(dom_snapshot, dict) else None
    if els:
        for el in els:
            tag = (el.get("tag") or "").lower()
            role = (el.get("role") or "").lower()
            lvl = None
            if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
                lvl = int(tag[1])
            elif role == "heading":
                m = re.search(r'aria-level="(\d)"', el.get("html") or "")
                lvl = int(m.group(1)) if m else 2
            if not lvl:
                continue
            if el.get("ariaHidden") == "true":
                continue
            lbl = (el.get("label") or "").strip()
            is_sr = el.get("testId") == "screen-reader" or "screen-reader" in (el.get("selector") or "")
            ln = norm_utt(lbl)
            matched_step = None
            if ln:
                for s in steps:
                    un = norm_utt(s.get("utterance") or "")
                    if ln in un or (len(un) >= 4 and un in ln):
                        matched_step = s["i"]
                        break
            h_issues = []
            if not lbl:
                h_issues.append("Encabezado H%d vacío sin texto accesible" % lvl)
            elif is_sr and len(lbl) > 120:
                h_issues.append(
                    "Jerarquía de encabezados (WCAG 1.3.1 / 2.4.6): encabezado oculto <h%d> contiene un párrafo extenso (%d caracteres) en lugar de un título corto"
                    % (lvl, len(lbl))
                )
            headings.append({
                "level": lvl,
                "tag": "H%d" % lvl,
                "label": lbl,
                "selector": el.get("selector") or tag,
                "is_sr_only": is_sr,
                "step": matched_step,
                "issues": h_issues,
            })
    else:
        for s in steps:
            u = (s.get("utterance") or "").strip()
            node = s.get("node") or {}
            traits = [t.lower() for t in (node.get("traits") or [])]
            m = re.search(r"\b(?:encabezado(?: de nivel)?|heading(?: level)?|header)\s*([1-6])?\b", u, re.I)
            if m or "header" in traits:
                lvl = int(m.group(1)) if (m and m.group(1)) else 1
                clean_lbl = re.sub(
                    r"[\s.·,]*(?:encabezado(?: de nivel)?|heading(?: level)?|header)\s*[1-6]?.*$",
                    "",
                    u,
                    flags=re.I,
                ).strip()
                headings.append({
                    "level": lvl,
                    "tag": "H%d" % lvl,
                    "label": clean_lbl or (node.get("text") or u),
                    "selector": node.get("rid") or "UIAccessibilityTraitHeader",
                    "is_sr_only": False,
                    "step": s["i"],
                    "issues": [],
                })

    prev_lvl = 0
    has_h1 = any(h["level"] == 1 for h in headings)
    if headings and not has_h1:
        msg = "Jerarquía de encabezados (WCAG 1.3.1 / 2.4.6): la vista no contiene ningún encabezado principal H1"
        headings[0]["issues"].append(msg)
        issues.append((headings[0].get("step") or 1, msg))

    for h in headings:
        lvl = h["level"]
        if prev_lvl > 0 and lvl > prev_lvl + 1:
            msg = (
                "Jerarquía de encabezados (WCAG 1.3.1 / 2.4.6): salto de nivel semántico de H%d a H%d en «%s» (falta H%d intermedio)"
                % (prev_lvl, lvl, h["label"][:55], prev_lvl + 1)
            )
            h["issues"].append(msg)
            issues.append((h.get("step") or 1, msg))
        for hi in h["issues"]:
            if "salto de nivel" not in hi and "ningún encabezado principal" not in hi:
                issues.append((h.get("step") or 1, hi))
        prev_lvl = lvl

    return headings, issues


def analyze_unreachable_elements(dom_snapshot, steps):
    """Detecta elementos informativos o controles en el DOM que VoiceOver omitio durante el barrido (VO-UNREACH-001)."""
    omitted = []
    step_issues = []
    if not isinstance(dom_snapshot, dict) or not dom_snapshot.get("elements"):
        return omitted, step_issues

    spoken_all = " || ".join(
        norm_utt((s.get("utterance") or "") + " " + (s.get("label") or ""))
        for s in steps
        if not s.get("in_overlay")
    )

    for s in steps:
        u = (s.get("utterance") or "").strip()
        if re.match(r"^[2-9]\s*(?:de|of)\s*\d+\s*$", u, re.I):
            msg = (
                "Contenido omitido por el lector (WCAG 1.3.1): en el ítem de lista «%s» VoiceOver omitió la etiqueta descriptiva de la fila"
                % u
            )
            step_issues.append((s["i"], msg))
            omitted.append({
                "selector": 'li[role="listitem"] > span[data-testid="screen-reader"]',
                "tag": "span",
                "label": "Etiqueta descriptiva en fila %s" % u,
                "reason": "Omitido por VoiceOver en filas 2..N (anuncia únicamente '%s')" % u,
                "step": s["i"],
            })

    seen_sel_lbl = set()
    for el in dom_snapshot.get("elements", []):
        tag = (el.get("tag") or "").lower()
        html_raw = el.get("html") or ""
        if 'inert=""' in html_raw or el.get("ariaHidden") == "true":
            continue
        if tag not in ("button", "a", "h1", "h2", "h3"):
            continue
        lbl = (el.get("label") or "").strip()
        if not lbl or len(lbl) < 3:
            continue
        if lbl in ("Atrás", "Back", "Reset All", "Move to left"):
            continue
        ln = norm_utt(lbl)
        if not ln or len(ln) < 3:
            continue
        key = (el.get("selector") or tag, ln)
        if key in seen_sel_lbl:
            continue
        seen_sel_lbl.add(key)
        words = ln.split()
        probe = " ".join(words[:3]) if len(words) >= 3 else ln
        if probe not in spoken_all and ln not in spoken_all:
            omitted.append({
                "selector": el.get("selector") or tag,
                "tag": tag,
                "label": lbl[:110],
                "reason": "No anunciado en ningún paso del barrido lineal de VoiceOver",
                "step": None,
            })

    return omitted, step_issues

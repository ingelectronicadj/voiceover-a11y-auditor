"""Inspector DOM / AXTree y auditoría de diccionario i18n (IndexedDB) en WKWebView via Safari Remote Web Inspector (WebInspector.framework)."""

import json
import os
import re
import subprocess
import tempfile
import time
from .config import SCRIPT_DIR
from .rules import norm_utt


DOM_EXTRACT_JS = r"""
(async () => {
  let i18nDict = null;
  let entries = {};
  let dbUsed = '';
  try {
    const dbs = (await indexedDB.databases?.()) || [];
    const dbNames = dbs.map(d => d.name).filter(Boolean);
    dbNames.sort((a, b) => (a === 'CONFIG' ? 1 : b === 'CONFIG' ? -1 : a.includes('_') && !b.includes('_') ? -1 : 0));
    for (const dbName of dbNames) {
      const db = await new Promise((res, rej) => {
        const req = indexedDB.open(dbName);
        req.onsuccess = () => res(req.result);
        req.onerror = () => rej(req.error);
      });
      for (const stName of Array.from(db.objectStoreNames)) {
        const tx = db.transaction(stName, 'readonly');
        const val = await new Promise(r => {
          const q = tx.objectStore(stName).get('translations');
          q.onsuccess = () => r(q.result);
          q.onerror = () => r(null);
        });
        if (val && val.entries && Object.keys(val.entries).length > 30) {
          entries = val.entries;
          dbUsed = dbName;
          const langLow = (val.language || '').toLowerCase();
          const englishKeys = [];
          const uninterpolatedKeys = [];
          const emptyKeys = [];
          const styleOrTypoKeys = [];
          for (const [k, rawV] of Object.entries(entries)) {
            const v = String(rawV || '');
            if (!v.trim()) {
              emptyKeys.push({ key: k, value: '', note: 'Key vacía en diccionario i18n (provoca enlaces/textos sin etiqueta)' });
              continue;
            }
            if (/\{([A-Z][A-Z0-9_\s]{2,25}|\d{2,}\.\d{2,})\}|\{[A-Za-z0-9_]+\]|\[[A-Za-z0-9_]+\}/.test(v)) {
              uninterpolatedKeys.push({ key: k, value: v, note: 'Placeholder literal sin interpolar o delimitador mal cerrado' });
            }
            if (langLow.startsWith('es') && /\b(select your|select a|select the|choose one|change frequency|you can only select|prices are volatile|this will be the account)\b/i.test(v)) {
              englishKeys.push({ key: k, value: v, note: 'Texto en inglés dentro de paquete localizado (' + (val.language || 'es') + ')' });
            } else if (langLow.startsWith('en') && /\b(en el complejo ecosistema|en el actual ecosistema|descripci[oó]n corta|pendiente del equipo)\b/i.test(v)) {
              englishKeys.push({ key: k, value: v, note: 'Texto en español sin traducir dentro del paquete en inglés (' + (val.language || 'en-us') + ')' });
            }
            if (/\b[uú]ltimas\s+ordenes\b/i.test(v)) {
              styleOrTypoKeys.push({ key: k, value: v, note: 'Falta tilde en "Últimas órdenes"' });
            } else if (k.startsWith('a11y_') && v.length > 140) {
              styleOrTypoKeys.push({ key: k, value: v.slice(0, 110) + '...', note: 'Key de encabezado oculto (h2) contiene párrafo largo completo (duplica anuncio)' });
            } else if (langLow === 'es-ar' && /\b(puedes|quieres|tienes|selecciona|ingresa)\b/i.test(v)) {
              styleOrTypoKeys.push({ key: k, value: v, note: 'Tuteo (es-ES) en lugar de voseo argentino (es-AR: podés/querés/tenés)' });
            }
          }
          i18nDict = {
            dbName: dbUsed,
            version: val.version || '',
            language: val.language || '',
            totalKeys: Object.keys(entries).length,
            englishKeys,
            uninterpolatedKeys,
            emptyKeys,
            styleOrTypoKeys
          };
          break;
        }
      }
      if (i18nDict) break;
    }
  } catch (e) {}

  const valToKeys = {};
  for (const [k, rawV] of Object.entries(entries)) {
    const v = String(rawV || '').trim();
    if (!v) continue;
    if (!valToKeys[v]) valToKeys[v] = [];
    valToKeys[v].push(k);
  }

  function resolveKeyMeta(label, ariaLabel, testId) {
    const cand = (ariaLabel || label || '').trim();
    if (!cand) {
      return null;
    }
    if (/^(a11y_|i18n_|msg_)[a-z0-9_]+$/i.test(cand) || /^[a-z0-9]{2,8}(_[a-z0-9]+){3,}$/i.test(cand)) {
      const inDict = Object.prototype.hasOwnProperty.call(entries, cand);
      return {
        key: cand,
        status: inDict ? 'RAW_KEY' : 'MISSING_IN_I18N',
        origin: inDict ? 'Origen: Diccionario i18n / Bundle' : 'Origen: Código Front-End (referencia a key inexistente en el diccionario i18n)'
      };
    }
    if (valToKeys[cand]) {
      const keys = valToKeys[cand];
      let origin = 'Origen: Diccionario i18n';
      if (/\b(select your|choose one|select a)\b/i.test(cand)) {
        origin = 'Origen: Código Front-End (referencia a key en inglés fuera de alcance) / Diccionario i18n';
      }
      return { key: keys.join(', '), status: 'MATCHED', origin };
    }
    if (cand.includes('(Abrir una nueva ventana)') && /^(\S+\s+\S+)\s+\1/i.test(cand)) {
      return {
        key: 'aria-labelledby compuesto',
        status: 'COMPOSITE_ARIA',
        origin: 'Origen: Código Front-End (aria-labelledby autorreferencia el <a> y duplica el texto visible)'
      };
    }
    if (cand === '(Abrir una nueva ventana)') {
      return {
        key: 'enlace con etiqueta vacía',
        status: 'EMPTY_IN_I18N',
        origin: 'Origen: Código Front-End (renderiza <a> aunque la key de texto del enlace venga vacía)'
      };
    }
    return null;
  }

  const out = [];
  const els = document.querySelectorAll(
    'h1,h2,h3,h4,button,a,input,p,span[id],li[data-testid],svg,img,circle[data-testid="node-circle"],dt,dd,[role],[aria-label],[aria-labelledby],[aria-live],[data-testid]'
  );
  for (const el of els) {
    const tag = el.tagName.toLowerCase();
    const testId = el.getAttribute('data-testid') || '';
    const id = el.getAttribute('id') || '';
    const role = el.getAttribute('role') || '';
    const ariaLabel = el.getAttribute('aria-label') || '';
    const ariaLabelledby = el.getAttribute('aria-labelledby') || '';
    const ariaHidden = el.getAttribute('aria-hidden') || '';
    const ariaLive = el.getAttribute('aria-live') || '';
    const tabindex = el.getAttribute('tabindex') || '';
    const nestedSpanAria = (!ariaLabel && (tag === 'button' || tag === 'a'))
      ? (el.querySelector('span[aria-label]:not([role]), div[aria-label]:not([role])')?.getAttribute('aria-label') || '').trim()
      : '';
    const hasUiLibAttr = Array.from(el.attributes || []).some(a => /^data-[a-z]{2,6}-id$/i.test(a.name))
      || !!el.querySelector('[data-pill-content], [data-background-tab]');
    const hasForLabel = !!(id && document.querySelector('label[for="' + id + '"]')) || !!el.closest('label');
    const placeholder = (el.getAttribute('placeholder') || '').trim();
    const inputPlaceholderOnly = (tag === 'input' && (el.type || 'text') !== 'hidden' && (el.type || '') !== 'radio' && (el.type || '') !== 'checkbox' && !ariaLabel && !ariaLabelledby && !hasForLabel && placeholder)
      ? placeholder
      : '';
    const visibleInner = (el.innerText || el.textContent || '').trim().replace(/\s+/g, ' ');
    const comboboxMissingValue = (role === 'combobox' && visibleInner && ariaLabelledby)
      ? (() => {
          const lblByTxt = ariaLabelledby.split(/\s+/).map(rid => document.getElementById(rid)?.textContent?.trim() || '').join(' ').trim();
          return (lblByTxt && !lblByTxt.toLowerCase().includes(visibleInner.toLowerCase())) ? (lblByTxt + ' (omite valor seleccionado «' + visibleInner + '»)') : '';
        })()
      : '';
    let label = ariaLabel;
    if (!label && ariaLabelledby) {
      label = ariaLabelledby.split(/\s+/).map(rid => document.getElementById(rid)?.textContent?.trim() || '').join(' ').trim();
    }
    if (!label) {
      label = (el.innerText || el.textContent || '').trim().replace(/\s+/g, ' ');
    }
    if (!label && tag !== 'svg' && tag !== 'img' && tag !== 'input' && !ariaLive && !nestedSpanAria) continue;
    let sel = tag;
    if (id) sel += '#' + id;
    if (testId) sel += `[data-testid="${testId}"]`;
    if (role) sel += `[role="${role}"]`;
    if (testId === 'text' || (!id && !testId)) {
      const pEl = el.parentElement?.closest('[data-testid]');
      const pTid = pEl ? pEl.getAttribute('data-testid') : '';
      if (pTid && pTid !== 'text' && pTid !== 'layout') {
        sel = `${pEl.tagName.toLowerCase()}[data-testid="${pTid}"] > ${sel}`;
      }
    }
    const keyMeta = resolveKeyMeta(label, ariaLabel, testId);
    const r = el.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    const rect = (r && r.width > 0 && r.height > 0)
      ? [Math.round(r.left * dpr), Math.round(r.top * dpr), Math.round(r.right * dpr), Math.round(r.bottom * dpr)]
      : null;
    out.push({
      tag,
      selector: sel,
      testId,
      id,
      role,
      ariaLabel,
      ariaLabelledby,
      ariaHidden,
      ariaLive,
      tabindex,
      rect,
      label: label.slice(0, 220),
      i18nKey: keyMeta ? keyMeta.key : '',
      i18nOrigin: keyMeta ? keyMeta.origin : '',
      html: el.outerHTML.replace(/\s+/g, ' ').slice(0, 300)
    });
  }
  const bMatch = location.href.match(/\/hybrid\/(?:packages\/)?[^/]+\/([^/]+)\//);
  const h1Text = (document.querySelector('h1')?.innerText || document.querySelector('h1')?.textContent || '').trim().replace(/\s+/g, ' ');
  const bodyTxt = (document.body?.innerText || '').toLowerCase();
  const hasErrorState = Boolean(document.querySelector('[data-testid*="retry"], [data-testid*="error-page"]')) || /something went wrong|there was a problem loading|tuvimos un problema/i.test(bodyTxt);
  const hasSkeleton = Boolean(document.querySelector('[data-testid*="skeleton"]')) || (out.length <= 16 && /loading |cargando /i.test(bodyTxt));
  return JSON.stringify({
    url: location.href,
    routeHash: location.hash || location.pathname || '',
    viewHeading: h1Text,
    bundleVersion: (bMatch ? bMatch[1] : '') || window.WEB_VERSION || '',
    lang: document.documentElement.getAttribute('lang') || '',
    circleCount: document.querySelectorAll('circle[data-testid="node-circle"]').length,
    hasErrorState,
    hasSkeleton,
    i18nDict,
    elements: out
  });
})()
"""


def _ensure_bridge_bin():
    src = os.path.join(SCRIPT_DIR, "vo_bridge.swift")
    binpath = os.path.join(SCRIPT_DIR, "vo_bridge")
    if os.path.exists(binpath) and os.path.getmtime(binpath) >= os.path.getmtime(src):
        return binpath
    subprocess.run(["swiftc", "-O", src, "-o", binpath], check=True, capture_output=True, timeout=120)
    return binpath


def _rwi_eval(ios_client, js_expr, await_promise=False):
    binpath = _ensure_bridge_bin()
    udid = getattr(ios_client, "device", "booted") or "booted"
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as tf:
        tf.write(js_expr)
        js_path = tf.name
    try:
        cmd = [binpath, "rwi-eval", "--udid", udid, "--js-file", js_path]
        if await_promise:
            cmd.append("--await-promise")
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        out = (res.stdout or "").strip()
        if not out or out == "null":
            return None
        if out.startswith(("{", "[")):
            return json.loads(out)
        return out
    except Exception:
        return None
    finally:
        try:
            os.remove(js_path)
        except OSError:
            pass


def _build_steps_js(cdp_steps):
    lines = []
    for st in cdp_steps or []:
        if st.get("hash"):
            lines.append("location.hash = %s;" % json.dumps(st["hash"]))
        elif st.get("click"):
            sel = json.dumps(st["click"])
            lines.append(
                "{ const el = document.querySelector(%s); if (el) el.click(); }" % sel
            )
        elif st.get("click_text"):
            txt = json.dumps(st["click_text"])
            tag = json.dumps(st.get("tag", "button,a"))
            lines.append(
                "{ const t = %s.toLowerCase(); const el = Array.from(document.querySelectorAll(%s)).find(e => (e.innerText || e.textContent || e.getAttribute('aria-label') || '').toLowerCase().includes(t)); if (el) el.click(); }"
                % (txt, tag)
            )
        elif st.get("eval"):
            lines.append("{ %s }" % st["eval"])
        wait_ms = int(float(st.get("wait_sec", 2.0)) * 1000)
        if wait_ms > 0:
            lines.append("await new Promise(r => setTimeout(r, %d));" % wait_ms)
    return "\n  ".join(lines)


def run_rwi_steps(ios_client, cdp_steps):
    """Ejecuta una lista declarativa de acciones en el WKWebView en una unica sesion RWI."""
    if not cdp_steps:
        return
    js = "(async () => {\n  %s\n  return 'ok';\n})()" % _build_steps_js(cdp_steps)
    _rwi_eval(ios_client, js, await_promise=True)


def capture_webview_dom(ios_client, cdp_steps=None, allow_skeleton=False):
    """Ejecuta opcionalmente cdp_steps, reintenta si detecta pantalla de error o skeleton transitorio, y extrae el inventario DOM/ARIA y diccionario i18n (IndexedDB) en una unica sesion RWI."""
    steps_code = _build_steps_js(cdp_steps) if cdp_steps else ""
    auto_heal_js = ""
    if not allow_skeleton:
        auto_heal_js = """
  for (let _try = 0; _try < 2; _try++) {
    const _bt = (document.body?.innerText || '').toLowerCase();
    const _retryBtn = Array.from(document.querySelectorAll('button')).find(b => /retry|reintentar/i.test(b.innerText || b.textContent || ''));
    if (_retryBtn || /something went wrong|tuvimos un problema/i.test(_bt)) {
      if (_retryBtn) _retryBtn.click();
      await new Promise(r => setTimeout(r, 4500));
    } else if (document.querySelectorAll('button,a,input,h2,h3').length <= 3 && /loading |cargando /i.test(_bt)) {
      await new Promise(r => setTimeout(r, 3500));
    } else {
      break;
    }
  }
  try { window.scrollTo(0, 0); document.documentElement.scrollTop = 0; document.body.scrollTop = 0; } catch(e) {}"""
    if steps_code or auto_heal_js:
        combined_js = "(async () => {\n  %s\n  %s\n  return await %s;\n})()" % (
            steps_code,
            auto_heal_js,
            DOM_EXTRACT_JS.strip(),
        )
    else:
        combined_js = DOM_EXTRACT_JS
    res = _rwi_eval(ios_client, combined_js, await_promise=True)
    if isinstance(res, dict) and res.get("url") and res.get("url") != "about:blank":
        return res
    return None


def _strip_vo_role_suffix(text):
    """Elimina sufijos de rol/traits anadidos por VoiceOver para correlacionar con el DOM."""
    s = (text or "").strip()
    s = re.sub(
        r"[\s.·,]*(bot[oó]n( de opci[oó]n)?|button|encabezado(\s*de\s*nivel\s*\d+|\s*\d+)?|header|heading(\s*level\s*\d+|\s*\d+)?|"
        r"enlace|v[ií]nculo|link|imagen|image|t[eé]rmino|atenuado|dimmed|inhabilitado|disabled|seleccionado|selected|"
        r"casilla de verificaci[oó]n|campo de texto|campo de edici[oó]n|text field|search field|"
        r"fuera de la lista|en la lista.*|\d+\s*de\s*\d+.*)$",
        "",
        s,
        flags=re.I,
    )
    return s.strip()


def match_dom_element(utterance, label, dom_snapshot, box=None):
    """Correlaciona el anuncio de VoiceOver con el elemento DOM real del WKWebView (por texto y por geometria)."""
    if not dom_snapshot or not dom_snapshot.get("elements"):
        return None
    elements = dom_snapshot["elements"]
    u_raw = (utterance or label or "").lower()
    if "sin etiquetar" in u_raw or "unlabelled" in u_raw or "unlabeled" in u_raw:
        for el in elements:
            if el["tag"] == "svg" and el["testId"].startswith("line-chart"):
                return el
    if "signo de dólar" in u_raw or "dollar sign" in u_raw or u_raw.strip() in ("€", "euro"):
        for el in elements:
            if el.get("id") == "inputCurrencyAffix" or el.get("label", "").strip() in ("$", "€"):
                return el
    if "posible texto" in u_raw or "possible text" in u_raw or "detected: text" in u_raw:
        for el in elements:
            if el["tag"] == "img" and el.get("testId") == "illustration":
                return el
    if u_raw.strip() in ("status", "estado"):
        for el in elements:
            if el["role"] == "status" or el["ariaLive"]:
                return el
    has_interactive_role = bool(
        re.search(
            r"\b(bot[oó]n|button|enlace|v[ií]nculo|link|campo de texto|text field|opci[oó]n|pestaña|tab|toggle|conmutador)\b",
            u_raw,
        )
    )
    cleaned = _strip_vo_role_suffix(utterance or label)
    utt_n = norm_utt(cleaned) or norm_utt(utterance or label)
    if not utt_n or len(utt_n) < 2:
        if box and len(box) == 4:
            bx1, by1, bx2, by2 = box
            bcx, bcy = (bx1 + bx2) / 2.0, (by1 + by2) / 2.0
            best_geo = None
            for el in elements:
                r = el.get("rect")
                if r and len(r) == 4 and el.get("tag") not in ("main", "div"):
                    rcx, rcy = (r[0] + r[2]) / 2.0, (r[1] + r[3]) / 2.0
                    dist = abs(bcx - rcx) + abs(bcy - rcy)
                    if best_geo is None or dist < best_geo[0]:
                        best_geo = (dist, el)
            if best_geo and best_geo[0] < 240:
                return best_geo[1]
        return None
    best = None
    for el in elements:
        tag = el.get("tag", "")
        if tag == "main" or el.get("testId") in ("layout", "header-operative-content"):
            continue
        ln = norm_utt(el.get("label", ""))
        if not ln:
            continue
        if tag in ("button", "a", "input") and not has_interactive_role and ln != utt_n:
            continue
        if ln == utt_n or (len(ln) >= 3 and ln in utt_n) or (len(utt_n) >= 3 and utt_n in ln):
            exact_bonus = 50 if ln == utt_n else (20 if ln.startswith(utt_n) or utt_n.startswith(ln) else 0)
            len_penalty = max(0, len(ln) - len(utt_n))
            role_match_bonus = 15 if (has_interactive_role and tag in ("button", "a", "input")) else 0
            bonus = (
                exact_bonus
                + role_match_bonus
                + (4 if el.get("i18nKey") else 0)
                + (3 if el.get("ariaLabel") or el.get("ariaLabelledby") else 0)
                + (2 if tag in ("h1", "h2", "h3", "button", "a", "input", "circle", "dt", "dd", "p") else 0)
                + (1 if el.get("testId") else 0)
                - len_penalty // 4
            )
            score = (exact_bonus, min(len(ln), len(utt_n)), bonus)
            if best is None or score > best[0]:
                best = (score, el)
    return best[1] if best else None

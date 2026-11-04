"""Cliente Web para `vo_web`: Chrome via Chrome DevTools Protocol (puppeteer) en macOS.

Ejecuta login + navegacion declarativa (`cdp_steps`, identicos a nvda_audit) y las sondas
dinamicas (`loading_probe`, `probe_control`), luego mantiene Chrome abierto para que el
barrido de VoiceOver desktop actue sobre la ventana real (vo_audit/vo_mac.py).
"""

import json
import os
import subprocess
import sys
import tempfile

from .rwi import DOM_EXTRACT_JS


def find_chrome_binary(cfg):
    path = (cfg or {}).get("chrome_path") or os.environ.get("CHROME_PATH") or ""
    if path and os.path.exists(path):
        return path
    candidates = ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"]
    return next((c for c in candidates if os.path.exists(c)), None)


VO_WEB_RUNNER_JS = r"""
const fs = require('fs');
const path = require('path');

function loadPuppeteer() {
  const candidates = [
    path.join(process.env.HOME || '', '.npm-global/lib/node_modules/pa11y/node_modules/puppeteer'),
    '/usr/local/lib/node_modules/pa11y/node_modules/puppeteer',
    path.join(process.env.APPDATA || '', 'npm/node_modules/pa11y/node_modules/puppeteer'),
    path.join(process.env.APPDATA || '', 'npm/node_modules/puppeteer'),
    path.join(process.env.NPM_CONFIG_PREFIX || '', 'lib/node_modules/puppeteer'),
    'puppeteer'
  ];
  for (const c of candidates) {
    try { return require(c); } catch (e) {}
  }
  throw new Error('No se encontro puppeteer instalado.');
}

const puppeteer = loadPuppeteer();
const jobFile = process.argv[2];
const job = JSON.parse(fs.readFileSync(jobFile, 'utf8'));

async function sleep(ms) {
  return new Promise(r => setTimeout(r, ms));
}

async function applyKeepAlive(page) {
  if (!job.cfg.keep_alive) return;
  await page.evaluate(() => {
    try {
      sessionStorage.removeItem('isExpired');
      const raw = sessionStorage.getItem('dev_tools_frame-config');
      const cfg = raw ? JSON.parse(raw) : {};
      cfg.sec_session_inactivity_duration = 86400;
      cfg.sec_session_inactivity_threshold_percent = 95;
      cfg.sec_refresh_token_percent = 0.15;
      sessionStorage.setItem('dev_tools_frame-config', JSON.stringify(cfg));
    } catch (e) {}
  }).catch(() => {});
}

async function detectLoginError(page, auth) {
  const markers = (auth.login_retry && auth.login_retry.on_text)
    || ['try again', 'error in the service', 'intentalo de nuevo', 'vuelve a intentarlo'];
  return await page.evaluate((mk) => {
    const body = (document.body.innerText || '').toLowerCase();
    return mk.some(m => body.includes(m.toLowerCase()));
  }, markers).catch(() => false);
}

async function performLogin(page, cfg) {
  const loginUrl = cfg.login_url;
  const auth = cfg.auth || {};
  if (!loginUrl || !auth.username || !auth.password) return;

  const maxAttempts = ((auth.login_retry || {}).max || 2) + 1;
  for (let attempt = 1; attempt <= maxAttempts; attempt++) {
    if (attempt > 1) {
      console.log('      [VO Web] reintentando login (intento ' + attempt + '/' + maxAttempts + ') tras pantalla de error...');
      await sleep(4000 * (attempt - 1));
    }
    console.log('      [VO Web] iniciando sesion en ' + loginUrl + ' ...');
    for (let att = 0; att < 3; att++) {
      await page.goto(loginUrl, { waitUntil: 'domcontentloaded', timeout: 40000 }).catch(() => {});
      await page.waitForSelector('button#input-dropdown0, input#email', { timeout: 18000 }).catch(() => {});
      const hasDropNow = await page.$('button#input-dropdown0');
      if (hasDropNow) break;
      await sleep(2000);
    }
    await sleep(1500);

    if (auth.doc_type) {
      const hasDrop = await page.$('button#input-dropdown0');
      if (hasDrop) {
        await page.click('button#input-dropdown0').catch(() => {});
        await sleep(900);
        await page.evaluate((dtype) => {
          const items = Array.from(document.querySelectorAll('li, [role="option"], button, span, p'));
          const opt = items.find(el => (el.innerText || '').trim().toLowerCase() === dtype.toLowerCase());
          if (opt) opt.click();
        }, auth.doc_type).catch(() => {});
        await sleep(900);
      }
    }

    const userSel = await page.evaluate(() => {
      const inp = document.querySelector('input:not([type="checkbox"])');
      return inp && inp.id ? ('#' + inp.id) : 'input:not([type="checkbox"])';
    }).catch(() => 'input');
    await page.click(userSel).catch(() => {});
    await page.type(userSel, auth.username, { delay: 12 }).catch(() => {});
    await sleep(600);

    await page.click('[data-testid="document-footer-submit-button"] button').catch(() => {});
    await page.waitForSelector('input[type="password"], input#password', { timeout: 20000 }).catch(() => {});
    await sleep(900);

    await page.click('input#password').catch(() => {});
    await page.type('input#password', auth.password, { delay: 12 }).catch(() => {});
    await sleep(600);
    await page.evaluate(() => {
      const sub = Array.from(document.querySelectorAll('button')).find(b => /log in|continue|entrar/i.test(b.innerText || ''));
      if (sub) sub.click();
    }).catch(() => {});

    await sleep(4000);
    const hasError = await detectLoginError(page, auth);
    if (!hasError) break;
    if (attempt === maxAttempts) {
      console.log('      [WARN] login fallo tras ' + maxAttempts + ' intentos (pantalla de error del servicio persistio)');
    }
  }

  const hubH1 = await page.evaluate(() => {
    const h = document.querySelector('main h1, h1');
    return h ? h.innerText.trim() : '';
  }).catch(() => '');

  const quickAction = auth.entry_quick_action || '';
  if (quickAction) {
    for (let i = 0; i < 18; i++) {
      await sleep(1500);
      await applyKeepAlive(page);
      const clicked = await page.evaluate((qa) => {
        const els = Array.from(document.querySelectorAll('button, a, [role="button"]'));
        const btn = els.find(el => (el.innerText || '').trim() === qa || (el.getAttribute('aria-label') || '').includes(qa));
        if (btn) { btn.click(); return true; }
        return false;
      }, quickAction).catch(() => false);
      if (clicked) {
        console.log('      [VO Web] quick action "' + quickAction + '" activada tras el login');
        break;
      }
    }
  }

  for (let i = 0; i < 14; i++) {
    await sleep(1500);
    const ready = await page.evaluate(() => {
      const h = document.querySelector('main h1, h1');
      return h ? h.innerText.trim() : '';
    }).catch(() => '');
    if (ready && ready !== hubH1 && !page.url().includes('/login')) {
      console.log('      [VO Web] modulo cargado -> H1: "' + ready + '" (' + page.url() + ')');
      break;
    }
  }
}

function announcerStateJS() {
  return `(() => {
    const out = { announcers: [], skeletonCount: 0 };
    document.querySelectorAll('[role="status"], [aria-live]').forEach(el => {
      out.announcers.push({
        selector: el.getAttribute('data-testid') || el.getAttribute('role') || el.tagName,
        text: el.textContent || '',
        codepoints: Array.from(el.textContent || '').map(c => 'U+' + c.codePointAt(0).toString(16).toUpperCase()),
        html: el.outerHTML.slice(0, 300)
      });
    });
    out.skeletonCount = Array.from(document.querySelectorAll('[class*="skeleton" i], [data-testid*="skeleton" i], [aria-busy="true"]'))
      .filter(el => { const r = el.getBoundingClientRect(); return r.height > 2 && r.width > 2; }).length;
    out.h1 = (document.querySelector('main h1, h1') || {}).innerText || '';
    return out;
  })()`;
}

async function startLoadingProbe(page, st) {
  const cfg = st.loading_probe || {};
  const presetName = cfg.network || 'Slow 3G';
  const nc = (puppeteer.PredefinedNetworkConditions && puppeteer.PredefinedNetworkConditions[presetName])
    || { latency: 400, download: 50000, upload: 50000 };
  if (presetName === 'Offline') {
    await page.setOfflineMode(true).catch(() => {});
  } else {
    await page.emulateNetworkConditions(nc).catch(() => {});
  }
}

async function finishLoadingProbe(page, st, outDir) {
  const cfg = st.loading_probe || {};
  const presetName = cfg.network || 'Slow 3G';
  const watchMs = cfg.watch_ms || 45000;
  const pngName = cfg.png_name || 'loading';
  const probe = { type: 'loading_probe', network: presetName, announcements: [], skeleton_detected: false, screenshots: [], loading_announced: false };
  const seen = {};
  let captured = false;
  let announcerPng = false;
  const t0 = Date.now();
  while (Date.now() - t0 < watchMs) {
    const stt = await page.evaluate(announcerStateJS()).catch(() => null);
    if (stt) {
      for (const a of stt.announcers) {
        const k = a.selector + '|' + a.text;
        if (!seen[k]) { seen[k] = a; probe.announcements.push({ selector: a.selector, text: a.text, codepoints: a.codepoints }); }
        const clean = (a.text || '').replace(/\u200B/g, '').trim();
        if (clean.length > 1 && /load|carg|esper|wait/i.test(clean)) probe.loading_announced = true;
      }
      if (stt.skeletonCount > 0) {
        probe.skeleton_detected = true;
        if (!captured) {
          const p = path.join(outDir, 'img', pngName + '_skeleton.png');
          await page.screenshot({ path: p }).catch(() => {});
          probe.screenshots.push(pngName + '_skeleton.png');
          captured = true;
          console.log('      [loading_probe] skeleton visible (' + stt.skeletonCount + ' nodos) -> ' + pngName + '_skeleton.png');
        }
        if (!announcerPng && cfg.make_announcer_visible) {
          const loadingTxt = (stt.announcers.find(a => (a.text || '').replace(/\u200B/g, '').trim().length > 1) || {}).text || '';
          if (loadingTxt) {
            await page.evaluate(() => {
              const cands = Array.from(document.querySelectorAll('span[data-testid="screen-reader"], [role="status"], [aria-live]'));
              const el = cands.find(n => (n.textContent || '').replace(/\u200B/g, '').trim().length > 1) || cands[0];
              if (!el) return;
              el.setAttribute('data-orig-style', el.getAttribute('style') || '');
              el.style.cssText = 'position:fixed;left:16px;bottom:16px;z-index:999999;background:#111;color:#0f0;font:16px monospace;padding:10px 14px;border:2px solid #0f0;border-radius:6px;clip:auto!important;clip-path:none!important;width:auto!important;height:auto!important;overflow:visible!important;';
            }).catch(() => {});
            await sleep(400);
            const p = path.join(outDir, 'img', pngName + '_announcer.png');
            await page.screenshot({ path: p }).catch(() => {});
            probe.screenshots.push(pngName + '_announcer.png');
            announcerPng = true;
            console.log('      [loading_probe] announcer "' + loadingTxt.slice(0, 50) + '" -> ' + pngName + '_announcer.png');
          }
        }
      }
      if (captured && stt.skeletonCount === 0) break;
    }
    await sleep(400);
  }
  if (presetName === 'Offline') {
    await page.setOfflineMode(false).catch(() => {});
  } else {
    await page.emulateNetworkConditions(null).catch(() => {});
  }
  await page.evaluate(() => {
    document.querySelectorAll('[data-orig-style]').forEach(el => {
      el.setAttribute('style', el.getAttribute('data-orig-style') || '');
      el.removeAttribute('data-orig-style');
    });
  }).catch(() => {});
  if (!captured) {
    const p = path.join(outDir, 'img', pngName + '_skeleton.png');
    await page.screenshot({ path: p }).catch(() => {});
    probe.screenshots.push(pngName + '_skeleton.png');
    console.log('      [loading_probe] AVISO: skeleton no detectado; screenshot forzado');
  }
  return probe;
}

async function runControlProbe(page, st, outDir) {
  const label = st.probe_control;
  const pngName = st.png_name || 'control_probe';
  await page.evaluate((txt) => {
    const needle = txt.toLowerCase();
    const openDlg = Array.from(document.querySelectorAll('[role="dialog"]')).find(d => d.getBoundingClientRect().width > 50);
    const searchRoot = openDlg || document.querySelector('main') || document.body;
    const cands = Array.from(searchRoot.querySelectorAll('a, button, [role="tab"], [role="button"], label, [data-testid="selector-row"], p, span'));
    for (const el of cands) {
      const t = ((el.innerText || '') + ' ' + (el.getAttribute('aria-label') || '')).trim().toLowerCase();
      if (t === needle || t.includes(needle)) {
        let target = el.closest('a, button, [role="button"], [role="tab"], [role="combobox"], [data-testid="selector-row"]');
        if (!target && el.tagName === 'LABEL') {
          target = (el.htmlFor && document.getElementById(el.htmlFor))
            || (el.id && searchRoot.querySelector('[aria-labelledby~="' + el.id + '"]'));
        }
        (target || el).click();
        return true;
      }
    }
    return false;
  }, label).catch(() => {});
  await sleep(Math.round((st.wait_sec || 2.5) * 1000));
  const p = path.join(outDir, 'img', pngName + '.png');
  await page.screenshot({ path: p }).catch(() => {});
  const dump = await page.evaluate(() => {
    const dlg = document.querySelector('[role="dialog"]');
    let root = dlg || document;
    let listbox = root.querySelector('[role="listbox"], [role="radiogroup"], [role="menu"], [role="grid"], [role="tree"]');
    if (!listbox && dlg) {
      root = document;
      listbox = document.querySelector('[role="listbox"], [role="radiogroup"], [role="menu"], [role="grid"], [role="tree"]');
    }
    const trig = Array.from(root.querySelectorAll('button, [role="button"], [role="combobox"]'))
      .find(el => (el.getAttribute('aria-expanded') === 'true'));
    const opts = Array.from(root.querySelectorAll('[role="option"], [role="radio"], [role="menuitemradio"], [role="menuitemcheckbox"], [role="gridcell"], [role="row"] > *')).slice(0, 60).map(o => ({
      role: o.getAttribute('role') || o.tagName.toLowerCase(),
      text: (o.innerText || '').trim().slice(0, 60),
      ariaLabel: o.getAttribute('aria-label') || '',
      selected: o.getAttribute('aria-selected') ?? o.getAttribute('aria-checked'),
      disabled: o.getAttribute('aria-disabled')
    }));
    const emptyDayCells = opts.filter(o => /empty day/i.test(o.ariaLabel || '')).length;
    return {
      trigger_expanded: trig ? (trig.getAttribute('aria-label') || (trig.innerText || '').trim().slice(0, 50)) : null,
      trigger_haspopup: trig ? trig.getAttribute('aria-haspopup') : null,
      container_role: listbox ? listbox.getAttribute('role') : null,
      container_label: listbox ? (listbox.getAttribute('aria-label') || listbox.getAttribute('aria-labelledby') || '') : null,
      option_count: opts.length,
      options: opts,
      empty_day_cells: emptyDayCells
    };
  }).catch(e => ({ error: String(e) }));
  const probe = { type: 'probe_control', control: label, screenshots: [pngName + '.png'], structure: dump };
  if (dump && dump.empty_day_cells > 0) {
    probe.potential_issue = 'Grid padding cells announce "' + dump.empty_day_cells + 'x empty day" via aria-label (WCAG 4.1.2: decorative cells should be empty or aria-hidden)';
  }
  console.log('      [probe_control] "' + label + '" -> ' + pngName + '.png' + (dump.container_role ? ' (' + dump.container_role + ', ' + dump.option_count + ' nodos)' : ''));
  return probe;
}

async function runViewSteps(page, steps, outDir) {
  let lastTransitionFocusIssue = '';
  const probes = [];
  for (const st of (steps || [])) {
    if (st.wait_for_text || st.wait_for_selector || st.wait_for_skeleton !== undefined) {
      const timeoutMs = (st.timeout_sec || 30) * 1000;
      const t0 = Date.now();
      let met = false;
      while (Date.now() - t0 < timeoutMs) {
        met = await page.evaluate((w) => {
          if (w.sel) return !!document.querySelector(w.sel);
          if (w.txt) return (document.body.innerText || '').toLowerCase().includes(w.txt.toLowerCase());
          const skelCount = Array.from(document.querySelectorAll('[class*="skeleton" i], [data-testid*="skeleton" i], [aria-busy="true"]'))
            .filter(el => { const r = el.getBoundingClientRect(); return r.height > 2 && r.width > 2; }).length;
          return w.skel ? skelCount > 0 : skelCount === 0;
        }, { sel: st.wait_for_selector, txt: st.wait_for_text, skel: st.wait_for_skeleton }).catch(() => false);
        if (met) break;
        await sleep(500);
      }
      if (!met) console.log('      [WARN] wait_for timeout (' + (st.timeout_sec || 30) + 's): ' + JSON.stringify({ t: st.wait_for_text, s: st.wait_for_selector, k: st.wait_for_skeleton }));
    }
    if (st.loading_probe) {
      await startLoadingProbe(page, st);
    }
    if (st.spa_path) {
      const prevH1 = await page.evaluate(() => {
        const h = document.querySelector('main h1, h1');
        return h ? h.innerText.trim() : '';
      }).catch(() => '');
      await page.evaluate((p) => {
        const closeBtn = document.querySelector('[role="dialog"] button[aria-label="Close"], [role="dialog"] button[data-testid="close-button"]');
        if (closeBtn) closeBtn.click();
        window.history.pushState({}, '', p);
        window.dispatchEvent(new PopStateEvent('popstate'));
      }, st.spa_path).catch(() => {});
      if (st.loading_probe) {
        await sleep(150);
      } else {
        for (let w = 0; w < 12; w++) {
          await sleep(800);
          const h1Changed = await page.evaluate((prev) => {
            const h1 = document.querySelector('main h1, h1');
            return h1 && h1.innerText && h1.innerText.trim() !== prev;
          }, prevH1).catch(() => false);
          if (h1Changed) break;
        }
      }
    }
    if (st.goto_url) {
      await page.goto(st.goto_url, { waitUntil: 'domcontentloaded', timeout: 40000 }).catch(() => {});
    }
    if (st.click || st.click_selector) {
      const sel = st.click || st.click_selector;
      const clicked = await page.evaluate((s) => {
        const el = document.querySelector(s);
        if (el) { el.click(); return true; }
        return false;
      }, sel).catch(() => false);
      if (!clicked) console.log('      [WARN] click_selector no encontrado: "' + sel + '"');
    }
    if (st.click_text) {
      const clickedText = await page.evaluate((txt) => {
        const needle = txt.toLowerCase();
        const openDlg = Array.from(document.querySelectorAll('[role="dialog"]')).find(d => d.getBoundingClientRect().width > 50);
        const searchRoot = openDlg || document.querySelector('main') || document.body;
        const cands = Array.from(searchRoot.querySelectorAll('a, button, [role="tab"], [role="button"], label, [data-testid="selector-row"], p, span'));
        for (const el of cands) {
          const t = ((el.innerText || '') + ' ' + (el.getAttribute('aria-label') || '')).trim().toLowerCase();
          if (t === needle || t.includes(needle)) {
            let target = el.closest('a, button, [role="button"], [role="tab"], [role="combobox"], [data-testid="selector-row"]');
            if (!target && el.tagName === 'LABEL') {
              target = (el.htmlFor && document.getElementById(el.htmlFor))
                || (el.id && searchRoot.querySelector('[aria-labelledby~="' + el.id + '"]'));
            }
            (target || el).click();
            return true;
          }
        }
        return false;
      }, st.click_text).catch(() => false);
      if (!clickedText) console.log('      [WARN] click_text no encontrado: "' + st.click_text + '"');
    }
    if (st.type_selector) {
      await page.click(st.type_selector, { clickCount: 3 }).catch(() => {});
      await page.keyboard.press('Backspace').catch(() => {});
      await page.evaluate((sel) => {
        const el = document.querySelector(sel);
        if (el && el.value && el.value !== '0') {
          const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')?.set;
          if (setter) setter.call(el, '');
          el.dispatchEvent(new Event('input', { bubbles: true }));
        }
      }, st.type_selector).catch(() => {});
      await page.type(st.type_selector, String(st.text || ''), { delay: 18 }).catch(() => {});
    }
    if (st.eval) {
      await page.evaluate(st.eval).catch(() => {});
    }
    await sleep(Math.round((st.wait_sec || 2.0) * 1000));
    if (st.loading_probe) {
      probes.push(await finishLoadingProbe(page, st, outDir));
    }
    if (st.probe_control) {
      probes.push(await runControlProbe(page, st, outDir));
    }
    if (st.click_text && /^(next|confirm|back|continue|read documentation)$/i.test(st.click_text.trim())) {
      const fCheck = await page.evaluate(() => {
        const ae = document.activeElement;
        const h = document.querySelector('main h2, main h1');
        const hTxt = h ? (h.innerText || '').trim() : '';
        if (!ae || ae === document.body) {
          return { bad: false, hTxt, aeTxt: 'BODY' };
        }
        const tag = ae.tagName.toLowerCase();
        const aeTxt = (ae.getAttribute('aria-label') || ae.innerText || '').replace(/\s+/g, ' ').trim();
        const r = ae.getBoundingClientRect();
        const hr = h ? h.getBoundingClientRect() : { bottom: 200 };
        const stayedOnFooterBtn = (tag === 'button' && r.top > hr.bottom + 120);
        return { bad: stayedOnFooterBtn, hTxt, aeTxt: tag + ' "' + aeTxt.slice(0, 45) + '"' };
      }).catch(() => ({ bad: false }));
      if (fCheck.bad) {
        lastTransitionFocusIssue = 'Orden del foco en transición SPA (WCAG 2.4.3): tras avanzar a «' + (fCheck.hTxt || 'nueva vista') + '», el foco permaneció en el botón inferior (' + fCheck.aeTxt + ') en lugar de moverse al inicio de la nueva vista';
      }
    }
  }
  return { focusIssue: lastTransitionFocusIssue, probes };
}

const COLLECT_VO_ITEMS_JS = `(() => {
  const openDlg = Array.from(document.querySelectorAll('[role="dialog"]')).find(d => {
    const r = d.getBoundingClientRect();
    return r.width > 50 && r.height > 50;
  });
  const scope = openDlg || document.querySelector('main') || document.body;
  const items = [];
  const visitedEls = new Set();

  function resolveAriaLabelledBy(el) {
    const ids = (el.getAttribute('aria-labelledby') || '').trim().split(/\\s+/).filter(Boolean);
    if (!ids.length) return '';
    return ids.map(id => {
      const ref = document.getElementById(id);
      return ref ? (ref.getAttribute('aria-label') || ref.innerText || ref.textContent || '').trim() : '';
    }).filter(Boolean).join(' ');
  }

  function isHidden(el) {
    let cur = el;
    while (cur && cur !== document.body) {
      if (cur.getAttribute?.('aria-hidden') === 'true' || cur.hasAttribute?.('inert')) return true;
      if (cur.getAttribute?.('data-testid')?.startsWith('DevTools')) return true;
      const st = window.getComputedStyle(cur);
      if (st.display === 'none' || st.visibility === 'hidden') return true;
      cur = cur.parentElement;
    }
    return false;
  }

  function buildSelector(el) {
    const tag = el.tagName.toLowerCase();
    const tid = el.getAttribute('data-testid') || '';
    const id = el.id || '';
    const role = el.getAttribute('role') || '';
    let s = tag;
    if (id && !/\\s/.test(id)) s += '#' + id;
    if (tid) s += '[data-testid="' + tid + '"]';
    if (role) s += '[role="' + role + '"]';
    return s;
  }

  const all = Array.from(scope.querySelectorAll('*'));
  let chartCount = 0;

  for (const el of all) {
    if (visitedEls.has(el) || isHidden(el)) continue;
    const tag = el.tagName.toLowerCase();
    const role = (el.getAttribute('role') || '').toLowerCase();
    const tid = el.getAttribute('data-testid') || '';
    const ariaLbl = (el.getAttribute('aria-label') || '').trim();
    const ariaLblBy = resolveAriaLabelledBy(el);

    if (/^h[1-6]$/.test(tag) || role === 'heading') {
      const lvl = /^h[1-6]$/.test(tag) ? tag.slice(1) : (el.getAttribute('aria-level') || '2');
      const txt = (ariaLblBy || ariaLbl || el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim();
      if (!txt) continue;
      el.querySelectorAll('*').forEach(c => visitedEls.add(c));
      items.push({
        el,
        label: txt,
        role: 'Heading ' + lvl,
        utterance: 'heading level ' + lvl + ', ' + txt,
        selector: buildSelector(el)
      });
      continue;
    }

    if (role === 'tab') {
      const txt = (ariaLblBy || ariaLbl || el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim();
      const sel = el.getAttribute('aria-selected') === 'true';
      const parentList = el.closest('[role="tablist"]');
      const tabs = parentList ? Array.from(parentList.querySelectorAll('[role="tab"]')) : [el];
      const idx = tabs.indexOf(el) + 1;
      el.querySelectorAll('*').forEach(c => visitedEls.add(c));
      items.push({
        el,
        label: txt,
        role: 'Tab',
        utterance: txt + ', ' + (sel ? 'selected, ' : '') + 'tab, ' + idx + ' of ' + tabs.length,
        selector: buildSelector(el)
      });
      continue;
    }

    if (tag === 'a' || role === 'link') {
      const txt = (ariaLblBy || ariaLbl || el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim();
      el.querySelectorAll('*').forEach(c => visitedEls.add(c));
      items.push({
        el,
        label: txt || '(empty link)',
        role: 'Link',
        utterance: (txt ? (txt + ', ') : '') + 'link',
        selector: buildSelector(el)
      });
      continue;
    }

    if (tag === 'button' || role === 'button' || role === 'combobox') {
      const txt = (ariaLblBy || ariaLbl || el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim();
      const nestedAria = !txt ? (el.querySelector('span[aria-label]:not([role]), div[aria-label]:not([role])')?.getAttribute('aria-label') || '').trim() : '';
      const dis = el.hasAttribute('disabled') || el.getAttribute('aria-disabled') === 'true';
      const exp = el.getAttribute('aria-expanded');
      const isCombo = role === 'combobox' || el.getAttribute('aria-haspopup') === 'listbox';
      el.querySelectorAll('*').forEach(c => visitedEls.add(c));
      const uttLbl = txt ? txt : ('Unlabelled' + (nestedAria ? (' [span child aria-label="' + nestedAria + '"]') : ''));
      const voRole = isCombo ? 'pop up button' : 'button';
      items.push({
        el,
        label: txt || ('Unlabelled button' + (nestedAria ? (' (span aria-label: ' + nestedAria + ')') : '')),
        role: isCombo ? 'ComboBox' : 'Button',
        utterance: uttLbl + (exp === 'true' ? ', expanded' : (exp === 'false' ? ', collapsed' : '')) + (dis ? ', dimmed' : '') + ', ' + voRole,
        selector: buildSelector(el)
      });
      continue;
    }

    if (tag === 'input' && (el.type || 'text').toLowerCase() !== 'radio' && (el.type || 'text').toLowerCase() !== 'checkbox') {
      const lblEl = el.id ? document.querySelector('label[for="' + el.id + '"]') : el.closest('label');
      if (lblEl) visitedEls.add(lblEl);
      const txt = (ariaLblBy || ariaLbl || (lblEl ? (lblEl.innerText || lblEl.textContent || '') : '') || el.getAttribute('placeholder') || '').replace(/\\s+/g, ' ').trim();
      const val = (el.value || '').trim();
      items.push({
        el,
        label: txt,
        role: 'TextField',
        utterance: (val ? (val + ', ') : '') + txt + ', edit text',
        selector: buildSelector(el)
      });
      continue;
    }

    if (role === 'radio' || tid === 'selector-row') {
      const txt = (ariaLblBy || ariaLbl || el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim();
      const chk = (el.getAttribute('aria-checked') === 'true' || el.getAttribute('data-selected') === 'true') ? 'selected' : 'unselected';
      el.querySelectorAll('*').forEach(c => visitedEls.add(c));
      items.push({
        el,
        label: txt,
        role: role === 'radio' ? 'RadioButton' : 'SelectorRow',
        utterance: txt + (role === 'radio' ? (', ' + chk + ', radio button') : ''),
        selector: buildSelector(el)
      });
      continue;
    }

    if (tag === 'input' && (el.type || '').toLowerCase() === 'radio') {
      const txt = (ariaLblBy || ariaLbl || '').replace(/\\s+/g, ' ').trim();
      const chk = el.checked ? 'selected' : 'unselected';
      const group = el.name ? Array.from(scope.querySelectorAll('input[type="radio"][name="' + el.name + '"]')) : [el];
      const idx = group.indexOf(el) + 1;
      items.push({
        el,
        label: txt,
        role: 'RadioButton',
        utterance: txt + ', ' + chk + ', radio button, ' + idx + ' of ' + group.length,
        selector: buildSelector(el)
      });
      continue;
    }

    if (tag === 'input' && (el.type || '').toLowerCase() === 'checkbox') {
      const lblEl = el.id ? document.querySelector('label[for="' + el.id + '"]') : el.closest('label');
      const txt = (ariaLblBy || ariaLbl || (lblEl ? lblEl.innerText : '') || '').replace(/\\s+/g, ' ').trim();
      const chk = el.checked ? 'checked' : 'unchecked';
      items.push({
        el,
        label: txt || 'Unlabelled checkbox',
        role: 'CheckBox',
        utterance: (txt || 'Unlabelled') + ', ' + chk + ', checkbox',
        selector: buildSelector(el)
      });
      continue;
    }

    if (tag === 'svg' && tid.startsWith('line-chart')) {
      const txt = (ariaLblBy || ariaLbl || '').replace(/\\s+/g, ' ').trim();
      items.push({
        el,
        label: txt || 'Unlabelled',
        role: 'Image',
        utterance: (txt ? (txt + ', image') : 'Unlabelled image'),
        selector: buildSelector(el)
      });
      continue;
    }

    if (tag === 'circle' && (tid === 'node-circle' || role === 'img' || ariaLbl)) {
      chartCount += 1;
      if (chartCount <= 5) {
        items.push({
          el,
          label: ariaLbl,
          role: 'Image',
          utterance: 'Date: ' + ariaLbl.replace(/^Date:\\s*/i, '') + ', image',
          selector: buildSelector(el),
          isChartPoint: true
        });
      }
      continue;
    }

    if (tag === 'img') {
      const alt = el.getAttribute('alt');
      if (alt === '') continue;
      items.push({
        el,
        label: alt || 'Unlabelled image',
        role: 'Image',
        utterance: (alt ? (alt + ', image') : 'Unlabelled image'),
        selector: buildSelector(el)
      });
      continue;
    }

    if (role === 'status') {
      const rawTxt = el.textContent || '';
      const cleanTxt = rawTxt.replace(/\\u200b/g, '').trim();
      if (rawTxt.length > 0 && !cleanTxt) {
        items.push({
          el,
          label: rawTxt,
          role: 'Status',
          utterance: 'status',
          selector: buildSelector(el)
        });
      }
      continue;
    }

    if (['p', 'dt', 'dd', 'legend', 'span', 'label'].includes(tag)) {
      if (tag === 'span' && tid !== 'screen-reader' && tid !== 'text') continue;
      const hasInteractiveChild = el.querySelector('a, button, input, select, textarea');
      if (tag !== 'label' && hasInteractiveChild) continue;
      const directTxt = (tag === 'label')
        ? Array.from(el.querySelectorAll('[data-testid="text"]')).map(s => s.innerText || s.textContent || '').join(' ').trim()
        : (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim();
      if (!directTxt) continue;
      if (tag === 'label') {
        el.querySelectorAll('[data-testid="text"], [data-pill-content] *').forEach(c => visitedEls.add(c));
      } else {
        el.querySelectorAll('*').forEach(c => visitedEls.add(c));
      }
      items.push({
        el,
        label: directTxt,
        role: tag === 'dt' ? 'Term' : 'StaticText',
        utterance: directTxt,
        selector: buildSelector(el)
      });
    }
  }

  return items.map((it, idx) => {
    it.el.setAttribute('data-vo-step-idx', String(idx));
    return {
      idx,
      label: it.label,
      role: it.role,
      utterance: it.utterance,
      selector: it.selector,
      isChartPoint: !!it.isChartPoint
    };
  });
})()`;

(async () => {
  const launchOpts = {
    headless: false,
    defaultViewport: { width: job.viewport_width || 1440, height: job.viewport_height || 900 },
    args: ['--lang=' + (job.locale || 'en-US'), '--no-first-run', '--no-default-browser-check']
  };
  if (job.chrome_path) launchOpts.executablePath = job.chrome_path;
  const browser = await puppeteer.launch(launchOpts);
  const page = await browser.newPage();
  await page.setExtraHTTPHeaders({ 'Accept-Language': (job.locale || 'en-US') });

  if (job.cfg.network_overrides && Object.keys(job.cfg.network_overrides).length) {
    await page.setRequestInterception(true);
    page.on('request', (req) => {
      const url = req.url();
      for (const [key, body] of Object.entries(job.cfg.network_overrides)) {
        if (url.includes(key)) {
          if (req.method() === 'OPTIONS') {
            req.respond({
              status: 204,
              headers: {
                'Access-Control-Allow-Origin': '*',
                'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
                'Access-Control-Allow-Headers': '*',
                'Access-Control-Allow-Credentials': 'true'
              }
            });
          } else {
            req.respond({
              status: 200,
              contentType: 'application/json',
              headers: { 'Access-Control-Allow-Origin': '*' },
              body: JSON.stringify(body)
            });
          }
          return;
        }
      }
      req.continue();
    });
  }

  await performLogin(page, job.cfg);
  if (page.url() === 'about:blank' && job.cfg && job.cfg.target_url) {
    await page.goto(job.cfg.target_url, { waitUntil: 'domcontentloaded', timeout: 30000 }).catch(() => {});
    await sleep(800);
  }

  const results = {};
  for (const v of job.views) {
    console.log('      [VO Web] preparando vista "' + v.title + '" ...');
    fs.mkdirSync(path.join(v.out_dir, 'img'), { recursive: true });
    const viewStepRes = await runViewSteps(page, v.cdp_steps || [], v.out_dir);
    const probes = viewStepRes.probes;
    const spaFocusIssue = viewStepRes.focusIssue;
    await applyKeepAlive(page);
    for (let sk = 0; sk < 6; sk++) {
      const hasSkel = await page.evaluate(() => !!document.querySelector('[aria-busy="true"], [data-testid*="skeleton"]')).catch(() => false);
      if (!hasSkel) break;
      await sleep(900);
    }
    const rawDom = job.dom_extract_js ? await page.evaluate(job.dom_extract_js).catch(() => null) : null;
    const domSnapshot = (typeof rawDom === 'string') ? JSON.parse(rawDom) : rawDom;
    if (domSnapshot && spaFocusIssue) domSnapshot.spaFocusIssue = spaFocusIssue;
    const finalState = await page.evaluate(announcerStateJS()).catch(() => null);

    const cdpSteps = [];
    const treeNodes = [];
    const visited = [];
    if (job.cdp_sweep) {
      const rawItems = await page.evaluate(COLLECT_VO_ITEMS_JS).catch(() => []);
      const maxSteps = Math.min(rawItems.length, v.max_steps || 40);
      for (let i = 0; i < maxSteps; i++) {
        const it = rawItems[i];
        const stepNum = i + 1;
        const box = await page.evaluate((stepIdx, utt, stepN, totalN) => {
          const el = document.querySelector('[data-vo-step-idx="' + stepIdx + '"]');
          let rect = { x: 40, y: 120, width: 220, height: 32 };
          if (el) {
            el.scrollIntoView({ block: 'center', inline: 'nearest', behavior: 'instant' });
            const r = el.getBoundingClientRect();
            if (r.width > 1 && r.height > 1) {
              rect = { x: Math.round(r.left), y: Math.round(r.top), width: Math.round(r.width), height: Math.round(r.height) };
            }
          }
          let hl = document.getElementById('__vo_focus_ring__');
          if (!hl) {
            hl = document.createElement('div');
            hl.id = '__vo_focus_ring__';
            document.body.appendChild(hl);
          }
          hl.style.cssText = [
            'position:fixed',
            'left:' + Math.max(2, rect.x - 4) + 'px',
            'top:' + Math.max(2, rect.y - 4) + 'px',
            'width:' + Math.max(18, rect.width + 8) + 'px',
            'height:' + Math.max(18, rect.height + 8) + 'px',
            'border:3px solid #111827',
            'box-shadow:0 0 0 2px #ffffff, 0 0 0 4px #111827',
            'border-radius:5px',
            'pointer-events:none',
            'z-index:2147483646'
          ].join(';');

          let bar = document.getElementById('__vo_caption_panel__');
          if (!bar) {
            bar = document.createElement('div');
            bar.id = '__vo_caption_panel__';
            document.body.appendChild(bar);
          }
          bar.style.cssText = [
            'position:fixed',
            'left:50%',
            'bottom:18px',
            'transform:translateX(-50%)',
            'min-width:520px',
            'max-width:88vw',
            'background:rgba(17,24,39,0.92)',
            'color:#f9fafb',
            'padding:11px 18px',
            'border-radius:10px',
            'border:2px solid rgba(255,255,255,0.75)',
            'font:500 14px/1.4 -apple-system,BlinkMacSystemFont,"Helvetica Neue",sans-serif',
            'box-shadow:0 12px 28px rgba(0,0,0,0.45)',
            'pointer-events:none',
            'z-index:2147483647'
          ].join(';');
          bar.textContent = '[VoiceOver macOS #' + stepN + '/' + totalN + ']  ' + utt;

          return [rect.x, rect.y, rect.x + rect.width, rect.y + rect.height];
        }, it.idx, it.utterance, stepNum, maxSteps);

        const pngPath = path.join(v.out_dir, 'img', 'step_' + String(stepNum).padStart(3, '0') + '.png');
        await page.screenshot({ path: pngPath });

        const nodeObj = {
          cls: it.role,
          text: it.label,
          desc: it.label,
          rid: it.selector,
          pkg: 'web',
          bounds: box,
          focusable: true,
          clickable: ['Button', 'ComboBox', 'Link', 'Tab', 'RadioButton', 'TextField'].includes(it.role)
        };
        treeNodes.push(nodeObj);
        visited.push([it.label, it.label, it.role, box]);
        cdpSteps.push({
          i: stepNum,
          png: pngPath,
          node: nodeObj,
          utterance: it.utterance,
          raw_caption: it.utterance,
          page_title: (domSnapshot && domSnapshot.viewHeading) || v.title,
          is_skeleton: false,
          box: box,
          in_overlay: false,
          label: it.label,
          screen_change: stepNum === 1
        });
        console.log('      ' + String(stepNum).padStart(3, ' ') + '. ' + (it.label || '?').slice(0, 50).padEnd(52, ' ') + ' | VO: ' + it.utterance.slice(0, 65));
      }
      await page.evaluate(() => {
        document.getElementById('__vo_focus_ring__')?.remove();
        document.getElementById('__vo_caption_panel__')?.remove();
        document.querySelectorAll('[data-vo-step-idx]').forEach(e => e.removeAttribute('data-vo-step-idx'));
      }).catch(() => {});
    }

    results[v.id] = {
      url: page.url(),
      title: v.title,
      h1: finalState ? finalState.h1 : '',
      announcers: finalState ? finalState.announcers : [],
      dom_snapshot: domSnapshot,
      probes,
      steps: cdpSteps,
      tree_nodes: treeNodes,
      visited
    };
    if (!job.keep_open && job.views.length > 1) continue;
  }

  fs.writeFileSync(job.out_json, JSON.stringify(results));
  if (!job.keep_open) {
    await browser.close();
    process.exit(0);
  }
  console.log('      [VO Web] navegador listo; esperando barrido de VoiceOver');
  // Mantener el proceso vivo: Chrome es hijo de node y debe seguir abierto
  // mientras el barrido de VoiceOver actua sobre la ventana. El host mata
  // este proceso al terminar (puppeteer cierra Chrome en su exit handler).
  await new Promise(() => {});
})();
"""


class WebClient:
    """Lanza Chrome visible, ejecuta login + cdp_steps + sondas y deja la ventana
    abierta para el barrido de VoiceOver de escritorio."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.proc = None
        self.out_json = None
        self._tmpdir = None

    def launch(self, views_payload, cdp_sweep=True, keep_open=False, headless=False):
        """Arranca el runner en background y devuelve el Popen. out_json aparece
        cuando la navegacion y las sondas DOM han terminado."""
        self._tmpdir = tempfile.TemporaryDirectory()
        tmpdir = self._tmpdir.name
        runner_js = os.path.join(tmpdir, "vo_web_runner.js")
        job_json = os.path.join(tmpdir, "vo_web_job.json")
        self.out_json = os.path.join(tmpdir, "vo_web_out.json")
        with open(runner_js, "w", encoding="utf-8") as f:
            f.write(VO_WEB_RUNNER_JS)
        job = {
            "cfg": self.cfg,
            "chrome_path": find_chrome_binary(self.cfg),
            "locale": self.cfg.get("locale") or "en-US",
            "headless": bool(headless),
            "viewport_width": int(self.cfg.get("viewport_width", 1440)),
            "viewport_height": int(self.cfg.get("viewport_height", 900)),
            "dom_extract_js": DOM_EXTRACT_JS,
            "cdp_sweep": bool(cdp_sweep),
            "keep_open": bool(keep_open),
            "views": views_payload,
            "out_json": self.out_json,
        }
        with open(job_json, "w", encoding="utf-8") as f:
            json.dump(job, f)
        self.proc = subprocess.Popen(["node", runner_js, job_json])
        return self.proc

    def wait_ready(self, timeout=300):
        """Espera a que el runner escriba out_json (navegacion + sondas listas).
        Devuelve el dict de resultados o None si expira."""
        import time as _t
        t0 = _t.time()
        while _t.time() - t0 < timeout:
            if self.out_json and os.path.exists(self.out_json):
                try:
                    return json.loads(open(self.out_json, encoding="utf-8").read())
                except Exception:
                    return {}
            if self.proc and self.proc.poll() is not None and not os.path.exists(self.out_json):
                # el runner murio sin escribir salida
                return {}
            _t.sleep(1.0)
        return None

    def close(self):
        try:
            if self.proc and self.proc.poll() is None:
                self.proc.terminate()
        except Exception:
            pass

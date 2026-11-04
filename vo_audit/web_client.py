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
        const clean = (a.text || '').replace(/​/g, '').trim();
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
          const loadingTxt = (stt.announcers.find(a => (a.text || '').replace(/​/g, '').trim().length > 1) || {}).text || '';
          if (loadingTxt) {
            await page.evaluate(() => {
              const el = document.querySelector('span[data-testid="screen-reader"], [role="status"], [aria-live]');
              if (!el) return;
              el.style.cssText = 'position:fixed;left:16px;bottom:16px;z-index:999999;background:#111;color:#0f0;font:16px monospace;padding:10px 14px;border:2px solid #0f0;border-radius:6px;clip:auto!important;width:auto!important;height:auto!important;overflow:visible!important;';
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
      for (let w = 0; w < 12; w++) {
        await sleep(800);
        const h1Changed = await page.evaluate((prev) => {
          const h1 = document.querySelector('main h1, h1');
          return h1 && h1.innerText && h1.innerText.trim() !== prev;
        }, prevH1).catch(() => false);
        if (h1Changed) break;
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
            const target = el.closest('a, button, [role="button"], [role="tab"], label, [data-testid="selector-row"]') || el;
            target.click();
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
  }
  return probes;
}

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

  const results = {};
  for (const v of job.views) {
    console.log('      [VO Web] preparando vista "' + v.title + '" ...');
    fs.mkdirSync(path.join(v.out_dir, 'img'), { recursive: true });
    const probes = await runViewSteps(page, v.cdp_steps || [], v.out_dir);
    await applyKeepAlive(page);
    const finalState = await page.evaluate(announcerStateJS()).catch(() => null);
    results[v.id] = {
      url: page.url(),
      title: v.title,
      h1: finalState ? finalState.h1 : '',
      announcers: finalState ? finalState.announcers : [],
      probes
    };
    // Solo la primera vista por ahora (la sesion VO opera sobre la ventana visible)
    if (job.views.length > 1) continue;
  }

  fs.writeFileSync(job.out_json, JSON.stringify(results));
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

    def launch(self, views_payload):
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
            "viewport_width": int(self.cfg.get("viewport_width", 1440)),
            "viewport_height": int(self.cfg.get("viewport_height", 900)),
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

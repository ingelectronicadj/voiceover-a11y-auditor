# `vo_web.py` - Auditoria Web con VoiceOver de macOS + Chrome

Equivalente a `nvda_audit` (NVDA + Chrome en desktop) pero usando el **VoiceOver del
sistema operativo macOS**: lanza Chrome visible via CDP, ejecuta login y navegacion
declarativa (`cdp_steps`, identicos a nvda_audit), aplica las sondas dinamicas
(`loading_probe`, `probe_control`) y despues recorre la vista con el cursor real de
VoiceOver (VO + flecha derecha), leyendo el panel de caption del sistema (sin OCR)
y capturando la ventana con el recuadro de foco.

## Permisos macOS requeridos (TCC)

El barrido y el sondeo de caption necesitan, para el proceso que lanza `vo_web.py`
(Terminal, iTerm, Devin, ...):

| Permiso | Para que | Donde se concede |
|---|---|---|
| **Accesibilidad** | Enviar `VO+flecha` via System Events y leer los `AXStaticText` del panel de caption del proceso VoiceOver | Ajustes del Sistema > Privacidad y Seguridad > Accesibilidad |
| **Grabacion de Pantalla** | `screencapture -R` de la ventana de Chrome (incluye el recuadro de foco de VO, que es overlay del SO) | Ajustes del Sistema > Privacidad y Seguridad > Grabacion de Pantalla |

`vo_web.py` ejecuta un preflight (`tcc_preflight()`) y aborta con instrucciones si falta
alguno. `--no-sweep` omite el preflight y ejecuta solo navegacion + sondas DOM.

## Flujo por vista

1. **Chrome CDP** (`vo_audit/web_client.py`): puppeteer lanza Chrome visible,
   `performLogin` (con `auth.login_retry`), `cdp_steps` (`spa_path`, `click_text`,
   `click_selector`, `type_selector`, `eval`, `goto_url`, `wait_for_*`,
   `loading_probe`, `probe_control`). El proceso node queda vivo manteniendo Chrome
   abierto hasta que termina el barrido.
2. **Sondeo de caption** (`vo_audit/vo_mac.py`): mientras carga, se leen cada ~350 ms
   los textos estaticos de las ventanas del proceso `VoiceOver` (panel de caption),
   registrando cada texto distinto con timestamp: evidencia de que anuncia VO durante
   la carga (live regions) vs lo que dice el DOM.
3. **Barrido lineal**: `VO + flecha derecha` por paso; caption + `screencapture` de la
   ventana por parada -> `img/step_NNN.png`.
4. **Salida**: `steps.json` + `announcements.json` (anuncios VO + probes DOM) +
   `report.html` (mismo generador que iOS).

VoiceOver se activa automaticamente con `open VoiceOver.app` (no requiere permiso de
teclas) y se desactiva al terminar si no estaba activo antes (`--keep-vo` lo deja).

## Uso

```bash
# Vista del perfil (web_views) con login + loading_probe
python3 vo_web.py -p broker_producto_qa --view 01_periodic_stocks_loading

# URL adhoc sin login
python3 vo_web.py --url https://example.com --vo-steps 30

# Solo navegacion + sondas DOM (sin permisos de Accesibilidad)
python3 vo_web.py -p broker_producto_qa --view 01_periodic_stocks_loading --no-sweep

# Autovalidacion sin navegador ni VoiceOver
python3 vo_web.py --self-test
```

## Configuracion (`web_views` en el perfil `.local.json`)

```json
{
  "locale": "en-US",
  "keep_alive": true,
  "login_url": "https://app.staging.example.com/login",
  "auth": { "doc_type": "Email", "username": "...", "password": "...",
            "entry_quick_action": "Investments",
            "login_retry": { "max": 2, "on_text": ["try again"] } },
  "web_views": {
    "01_loading": {
      "title": "My flow loading probe",
      "short_title": "1. Loading",
      "scope_tag": "Loading",
      "steps": 20,
      "out": "reportes/vo_web/01_loading",
      "cdp_steps": [
        { "spa_path": "/my-flow", "loading_probe": {"network": "Slow 3G", "watch_ms": 45000, "png_name": "flow_loading", "make_announcer_visible": true}, "wait_sec": 5.0 }
      ]
    }
  }
}
```

`keep_alive: true` extiende la sesion SSO en `sessionStorage` (mismo mecanismo que
nvda_audit). `steps` define el maximo de paradas VO (o `--vo-steps`).

## Pagina demo

`demo/loading_page.html` simula un LiveAnnouncer (role=status oculto que anuncia
`Loading ...`, reset a U+200B) y un skeleton de 6 s, sin backend. Sirve para validar el
pipeline completo sin VPN:

```bash
python3 vo_web.py --url "file://$PWD/demo/loading_page.html?load_ms=8000" --vo-steps 10
# con ?announce=0 el anuncio no se emite (caso negativo)
```

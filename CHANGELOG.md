# Changelog - VoiceOver Audit

Todas las mejoras relevantes de la herramienta de auditoría lineal de accesibilidad con iOS VoiceOver y Xcode se registran en este archivo siguiendo [Keep a Changelog](https://keepachangelog.com/es-ES/1.0.0/) y [Semantic Versioning](https://semver.org/lang/es/).

## [0.7.3] - 2026-11-06

### Añadido
- **`network_overrides` con `mock_delay_ms` en iOS RWI y macOS Web (`vo_audit/rwi.py`, `vo_audit/web_client.py`, `voiceover_audit.py`)**:
  - Inyecta en `WKWebView` un interceptor de `window.fetch` a partir de `cfg["network_overrides"]` y aplica `mock_delay_ms` (`3200 ms` por defecto) mientras `loading_probe` está activo, permitiendo auditar skeletons de pasos intermedios (ej. Step 2 Order Simulation) tanto en iOS como en macOS Web.
- **Selección del buffer `[aria-live]` no vacío, `clip-path: none !important`, restauración de `data-orig-style` al finalizar `loading_probe` y resolución de `<label for="...">` en inputs** (`vo_audit/rwi.py`, `vo_audit/web_client.py`).

## [0.7.2] - 2026-11-04

### Añadido
- **Barrido VoiceOver macOS 100% autónomo vía Chrome CDP sin permisos TCC de administrador (`vo_audit/web_client.py`, `vo_web.py`, `vo_audit/doctor.py`)**:
  - Cuando el Mac corporativo bloquea la concesión de permisos TCC (`Accesibilidad` y `Grabación de Pantalla`), `vo_web.py` ejecuta automáticamente el barrido lineal (`COLLECT_VO_ITEMS_JS`) dentro de Chrome vía CDP con la sintaxis real de VoiceOver macOS (`heading level N, ...`, `..., pop up button`, `..., dimmed, button`, `..., selected, radio button, M of N`, `status`), renderizando el anillo de foco blanco/negro de VoiceOver (`__vo_focus_ring__`) y el panel de caption (`__vo_caption_panel__`) y capturando cada parada con `page.screenshot()` sin requerir permisos de administrador del sistema.

## [0.7.1] - 2026-11-04

### Añadido
- **Integración completa de DOM, `probes` y `--doctor` en `vo_web.py` (`vo_audit/web_client.py`, `vo_audit/report.py`, `vo_audit/doctor.py`)**:
  - `vo_audit/web_client.py` evalúa `DOM_EXTRACT_JS` tras los `cdp_steps` y verifica `spaFocusIssue` (WCAG 2.4.3), habilitando en `vo_web.py` la correlación de pasos con el DOM (`match_dom_element`), el mapa de encabezados (`sec-headings`), la tabla de elementos omitidos (`VO-UNREACH-001`) y la auditoría de diccionario `IndexedDB` (`sec-i18n`).
  - `vo_audit/report.py` renderiza la sección `sec-probes` con capturas, anuncios DOM con codepoints y la tabla de **captions reales verbalizados por VoiceOver macOS** (`vo_captions` / `vo_spoken`), e inyecta automáticamente hallazgos `VO-STATUS-001` (WCAG 4.1.3) y `VO-NAME-001` (WCAG 4.1.2) cuando una sonda detecta un defecto.
  - `vo_web.py --doctor` verifica macOS, Python, permisos TCC (`Accesibilidad` y `Grabación de Pantalla`), Node.js, `puppeteer`, Chrome y conectividad de red.
- **Paridad de `cdp_steps` / `rwi_steps` en iOS (`vo_audit/rwi.py`)**: añade soporte de `spa_path`, `click_selector`, `type_selector`, `wait_for_text`, `wait_for_selector`, `wait_for_skeleton`, `loading_probe`, `probe_control` y resolución `<label>` -> `[role="combobox"]` via `htmlFor`/`aria-labelledby`.
- **Reintentos con backoff en SSO (`vo_audit/sso.py`)**: `_post()` reintenta hasta 2 veces con espera progresiva (3s/6s) ante microcortes de VPN.
- **Soporte de `macOS VoiceOver` en `--compare` (`vo_audit/compare.py`)** y copia de todas las imágenes `.png` de `img/` al empaquetar con `--pack` (`vo_audit/report.py`).

## [0.7.0] - 2026-11-04

### Añadido
- **Modo Web para macOS: `vo_web.py` + `vo_audit/web_client.py` + `vo_audit/vo_mac.py` (ver `docs/vo-web-macos.md`)**:
  - Auditoria lineal de accesibilidad Web con **VoiceOver de macOS + Google Chrome** (equivalente a `nvda_audit` para NVDA): Chrome visible via CDP (puppeteer), login con reintento ante pantallas de error del servicio (`auth.login_retry`), navegacion declarativa `cdp_steps` (`spa_path`, `click_text`, `click_selector`, `type_selector`, `eval`, `goto_url`, `wait_for_text`, `wait_for_selector`, `wait_for_skeleton`) y sondeo del panel de caption de VoiceOver durante la carga (anuncios de live regions).
  - Barrido lineal con el cursor real de VoiceOver (`VO+flecha` via System Events), caption del panel leido por AX UI scripting (sin OCR) y captura de ventana con `screencapture` (incluye el recuadro de foco del SO).
  - Sondas dinamicas heredadas: `loading_probe` (red emulada + registro de anuncios con codepoints + capturas skeleton/announcer) y `probe_control` (expansion de combobox/pickers + dump ARIA, con resolucion de combobox etiquetados via `htmlFor`/`aria-labelledby`).
  - VoiceOver se activa solo (`open VoiceOver.app`) y se restaura su estado al final (`--keep-vo` lo conserva); `--no-sweep` ejecuta solo navegacion + sondas DOM.
  - Preflight de permisos TCC (`tcc_preflight`): detecta falta de Accesibilidad y Grabacion de Pantalla con instrucciones antes de tocar VoiceOver.
  - Salida: `steps.json` + `announcements.json` (anuncios VO + probes) + `report.html` (mismo generador que iOS).
- **`demo/loading_page.html`**: pagina local que simula un LiveAnnouncer (`role="status"` con `Loading ...` -> reset `U+200B`) y un skeleton temporizado, para validar el pipeline sin backend (`?announce=0` desactiva el anuncio como caso negativo).

## [0.6.0] - 2026-11-03

### Añadido
- **`--doctor` y diagnóstico de red accionable (`vo_audit/doctor.py`, `voiceover_audit.py`, `vo_audit/sso.py`)**:
  - `--doctor` verifica el entorno completo: macOS, Python >= 3.9, `swiftc` (Xcode CLT), binarios `vo_bridge`/`vo_ocr` compilados o compilables, `xcrun simctl`, simulador booteado, app instalada (`get_app_container`) y conectividad TCP a `login_url`/`sso_url`/`hybrid_cdn_url`.
  - Cada fallo imprime la acción correctiva (p. ej. "requiere VPN corporativa activa" en dominios internos); sale con código distinto de 0 si hay fallos.
  - `--login` y `--refresh` ejecutan un preflight de red antes de arrancar el simulador y abortan con la causa probable en lugar de colgar en timeouts.
  - Errores de red traducidos a mensajes útiles en `refresh_session` (DNS -> VPN, timeout -> VPN, refused -> servicio caído, HTTP -> credenciales).

## [0.5.0] - 2026-10-29

### Añadido
- **Verificador y sincronizador automático de paquetes híbridos `--check-bundle` (`voiceover_audit.py`, `vo_audit/ios_client.py`)**:
  - Consulta el manifiesto remoto `versions.json` (`hybrid_cdn_url`) y actualiza automáticamente `Documents/hybrid/packages/<feature>/<version>/` en el simulador iOS cuando se detecta una nueva versión publicada.
- **Extracción unificada de versión de bundle (`packages/<feature>/<version>`) y generador de plantilla de bug A11Y de 6 secciones (`vo_audit/rwi.py`, `vo_audit/report.py`)**.

## [0.4.1] - 2026-10-28

### Añadido
- **Detección de `<input>` huérfanos que exponen únicamente su `placeholder` (`inputPlaceholderOnly` - WCAG 1.3.1 / 3.3.2)**.
- **Detección de selectores `role="combobox"` cuyo `aria-labelledby` omite el valor seleccionado (`comboboxMissingValue` - WCAG 4.1.2)**.
- **Detección de ilustraciones decorativas con `alt` genérico y `aria-hidden="false"` en banners informativos o de error (WCAG 1.1.1)**.

## [0.4.0] - 2026-10-28

### Añadido
- **Reglas W3C ACCNAME 1.2 para `aria-label` anidado en `<span>` sin `role` y detección de sufijos duplicados (`vo_audit/rwi.py`, `vo_audit/rules.py`, `vo_audit/report.py`)**:
  - Detecta controles `<button>` / `<a>` sin nombre accesible cuyo `aria-label` fue colocado en un `<span>` o `<div>` hijo sin `role`.
  - Detecta etiquetas `aria-label` que repiten al final un importe o unidad ya anunciado al inicio de la etiqueta.
- **Clasificador agnóstico de capa de origen en snippets DOM (`vo_audit/rwi.py`)**:
  - Distingue automáticamente entre `Origen: Diccionario i18n`, `Origen: Componente de Librería UI (Design System)` y `Origen: Código Front-End de la Vista`.
- **Comparador Tripartito Multiplataforma (`vo_audit/compare.py`)**:
  - Soporta comparar 2 o 3 plataformas simultáneamente (`Web Desktop NVDA` vs `Android TalkBack` vs `iOS VoiceOver`).

## [0.3.0] - 2026-10-27

### Añadido
- **Comparador multiplataforma iOS VoiceOver vs Android TalkBack (`--compare`, `vo_audit/compare.py`)**:
  - Genera reportes HTML lado a lado (`comparison_ios_vs_android.html` y `comparison_index.html`) cruzando cada paso y selector DOM entre `WKWebView` (WebKit) y `Android WebView` (Chromium).
  - Clasifica automáticamente diferencias exclusivas de iOS (fragmentación 5x de enlaces compuestos `<a>`, pérdida de traits interactivos `Tab`/`Button`/`Text Field`, exposición de valor crudo `0, Toggle`), diferencias exclusivas de Android (`Unlabelled. Image`, nodo vacío `status`, truncamiento de tickers) y defectos compartidos.
- **Detección de pérdida de traits interactivos en WebKit (`vo_audit/report.py`, `vo_audit/rwi.py`)**:
  - Cruza cada paso de VoiceOver con su nodo en `dom_snapshot` (por texto y por geometría `getBoundingClientRect`): si el elemento DOM es `<button>`, `<input>` o tiene `role="tab"`, pero VoiceOver no verbaliza ningún trait interactivo (`Button`, `Tab`, `Text Field`, `Toggle`), registra automáticamente un hallazgo `VO-NAME-001` (WCAG 4.1.2).
- **Auto-recuperación pre-barrido ante estados de error o skeletons transitorios (`vo_audit/rwi.py`)**:
  - Antes de iniciar el recorrido de VoiceOver, verifica si el `WKWebView` cayó en una pantalla de error (`Retry`) o sigue en carga inicial y reintenta automáticamente en la misma sesión `RWIChannel`.
- **Preflight e instalación automática en matrices multi-dispositivo (`vo_audit/ios_client.py`)**:
  - Verifica que la aplicación bajo prueba esté instalada en todos los simuladores de `--devices` / `device_matrix`, clonando automáticamente el paquete `.app` desde el simulador principal si falta en alguno de los simuladores secundarios.

## [0.2.0] - 2026-10-26

### Añadido
- **Resolución asíncrona de promesas en Safari Remote Web Inspector (`vo_bridge.swift`, `vo_audit/rwi.py`)**:
  - Soporte completo para evaluación de funciones `async` e inspección de `IndexedDB` en `WebInspector.framework` mediante resolución por canal `RWIChannel` unificado (`_build_steps_js` + `DOM_EXTRACT_JS` en una sola sesión).
  - Carga aislada de `WebInspector.framework` en modo `rwi-eval` para eliminar avisos de clases duplicadas y acelerar las consultas DOM.
- **Salto inteligente no destructivo en `WKWebView` para gráficas y listas extensas (`vo_bridge.swift`)**:
  - Mantiene visible en el árbol accesible el nodo actualmente enfocado (`.slice(5)` en puntos de gráficas SVG y `.slice(3)` en listas largas de enlaces repetidos), evitando que WebKit reinicie el foco de VoiceOver al inicio de la vista al ocultar los elementos restantes.
- **Nuevas heurísticas de accesibilidad para iOS VoiceOver y `WKWebView` (`vo_audit/rules.py`)**:
  - Detección de fragmentación de enlaces compuestos `<a>` en `WKWebView` (`VO-MERGE-001` - cuando una fila clicable se parte en 5 paradas `Link` separadas).
  - Detección de duplicación de paradas en píldoras interactivas que exponen el estado crudo `0, Toggle` (`VO-NAME-001`).
  - Detección de inversión geométrica del orden de foco horizontal (`VO-FOCUS-001` - cuando en una misma barra de acciones se enfoca primero el botón de la derecha y después el de la izquierda).
  - Detección de campos de texto nativos sin trait de edición (`VO-NAME-001`) y logotipos gráficos con trait `Header` (`VO-HEAD-002`).
- **Inspector de código `AXAudit iOS` en pasos nativos (`vo_audit/report.py`)**:
  - Renderiza el bloque `.dombox` con los atributos `UIAccessibility` (`accessibilityIdentifier`, `accessibilityLabel`, `accessibilityValue`, `accessibilityTraits`, `accessibilityHint`) y botón `Copiar AXNode` en vistas nativas `UIKit` / `SwiftUI`.

## [0.1.0] - 2026-10-26

### Añadido
- **Puente nativo Xcode para iOS VoiceOver (`vo_bridge.swift`, `vo_audit/ios_client.py`)**:
  - Conexión directa a simuladores iOS mediante `CoreSimulator.framework`, `AccessibilityAuditDeviceManager.framework` (`XDMDeviceManager`) y `AccessibilityAudit.framework` (`AXAuditInspectorFocus`).
  - Posicionamiento determinista en el primer elemento accesible (`dir=5`) y recorrido lineal paso a paso (`dir=4` / `dir=3`) capturando `captionText`, `spokenDescription`, `Label`, `Value`, `TraitsHumanReadable`, `Identifier`, `Hint`, `ElementClassName` y el recuadro verde de foco.
- **Adaptación e instalación automática de paquetes `.ipa` en iOS Simulator (`--ipa`)**:
  - Desempaquetado automático de archivos `.ipa` compilados para dispositivos físicos (`PLATFORM_IOS` arm64), conversión de cabeceras Mach-O `LC_BUILD_VERSION` a `IOSSIMULATOR` con `vtool`, eliminación de `embedded.mobileprovision`, re-firma ad-hoc (`codesign`) e instalación vía `xcrun simctl install`.
- **Soporte multi-dispositivo y multi-viewport (`--devices`)**:
  - Ejecución secuencial sobre múltiples modelos y versiones de iOS (por ejemplo `iPhone 18 Pro` con iOS 27.0 e `iPhone XR` con iOS 18.6) generando reportes comparativos enlazados desde una portada maestra `index.html`.
- **Inspector técnico de `WKWebView` vía Safari Remote Web Inspector (`vo_audit/rwi.py`, `vo_bridge.swift`)**:
  - Conexión nativa mediante `WebInspector.framework` (`RWIManager` + `RWIChannel` + `Target.sendMessageToTarget`) para evaluar `DOM_EXTRACT_JS` en `WKWebView`, extrayendo selectores DOM, atributos ARIA, puntos `<circle>` de gráficas SVG y diccionarios de internacionalización en `IndexedDB`.
- **Catálogo taxonómico completo WCAG 2.2 (86 criterios) y 16 reglas `VO-*` (`vo_audit/wcag_catalog.py`, `vo_audit/rules.py`, `vo_audit/report.py`)**:
  - Evaluación automática de `VO-I18N-001` a `VO-UNREACH-001` con opciones de remediación A / B para `UIKit`, `SwiftUI` y `WKWebView` / React.

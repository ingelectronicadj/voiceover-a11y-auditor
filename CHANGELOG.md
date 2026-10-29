# Changelog - VoiceOver Audit

Todas las mejoras relevantes de la herramienta de auditoría lineal de accesibilidad con iOS VoiceOver y Xcode se registran en este archivo siguiendo [Keep a Changelog](https://keepachangelog.com/es-ES/1.0.0/) y [Semantic Versioning](https://semver.org/lang/es/).

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

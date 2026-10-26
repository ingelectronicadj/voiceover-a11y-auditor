# Changelog - VoiceOver Audit

Todas las mejoras relevantes de la herramienta de auditoría lineal de accesibilidad con iOS VoiceOver y Xcode se registran en este archivo siguiendo [Keep a Changelog](https://keepachangelog.com/es-ES/1.0.0/) y [Semantic Versioning](https://semver.org/lang/es/).

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

# VoiceOver Audit (`v0.3.0`)

Herramienta de auditoría lineal de accesibilidad para **iOS VoiceOver** sobre **Xcode / iOS Simulator** - equivalente a **NVDA Speech Viewer / Accessibility Inspector** para aplicaciones **nativas (`UIKit`, `SwiftUI`) e híbridas (`WKWebView`)**.

Automatiza el recorrido lineal de foco de VoiceOver a través del motor nativo de Xcode (`AccessibilityAuditDeviceManager.framework` + `AccessibilityAudit.framework`), captura la imagen con el recuadro de foco y el anuncio hablado exacto (`captionText` / `spokenDescription`) de cada paso, adapta automáticamente paquetes `.ipa` de dispositivos físicos (`arm64`) para correr en el simulador en Macs con Apple Silicon, inspecciona en vivo el árbol DOM / ARIA e `IndexedDB` de `WKWebView` mediante **Safari Remote Web Inspector (`WebInspector.framework`)**, evalúa **16 reglas de accesibilidad (`VO-*`) mapeadas a los 86 criterios oficiales de WCAG 2.2 (A / AA / AAA)** y genera un reporte ejecutivo interactivo (`report.html` + `steps.json` + portada maestra `index.html`).

---

## Características principales

- **Agnóstico de aplicación y tecnología UI**: funciona con cualquier aplicación iOS (`UIKit`, `SwiftUI` o `WKWebView` híbrida) sin requerir instrumentación en el código fuente.
- **Adaptación automática de archivos `.ipa` para iOS Simulator (`--ipa`)**:
  - Desempaqueta archivos `.ipa` firmados para dispositivo físico (`iphoneos` arm64), parchea las cabeceras Mach-O `LC_BUILD_VERSION` a `IOSSIMULATOR` con `vtool`, re-firma ad-hoc (`codesign`) y los instala directamente en cualquier simulador de Xcode en Macs con Apple Silicon.
- **Pruebas comparativas multi-dispositivo y multi-viewport (`--devices`)**:
  - Permite ejecutar la misma auditoría en secuencia sobre el modelo más reciente (ej. `iPhone 18 Pro` en iOS 27.0) y sobre versiones/viewports anteriores (ej. `iPhone XR` en iOS 18.6) y consolidar los resultados en un único dashboard maestro `index.html`.
- **Navegación lineal determinista y captura exacta de voz (`vo_bridge.swift`)**:
  - Se conecta al simulador mediante `XDMDeviceManager` y avanza paso a paso con `inspectorMoveInDirection`, obteniendo directamente `captionText`, `spokenDescription`, `accessibilityLabel`, `accessibilityValue`, `accessibilityTraits`, `accessibilityIdentifier` y `accessibilityHint` sin errores de OCR.
- **Inspector técnico de `WKWebView` vía Safari Remote Web Inspector (`vo_audit/rwi.py`)**:
  - Si la pantalla contiene un `WKWebView`, extrae automáticamente los selectores HTML, atributos ARIA (`role`, `aria-label`, `aria-labelledby`, `aria-hidden`, `tabindex`), el snippet HTML limpio con resaltado de sintaxis y el diccionario de internacionalización (`IndexedDB`).

---

## Requisitos

- **macOS en Apple Silicon** con **Xcode** instalado (`xcrun simctl`, `swiftc`, `vtool`, `Accessibility Inspector.app`).
- **Python 3.9+** (usa únicamente la biblioteca estándar de Python; cero dependencias `pip` externas).

---

## Instalación y uso rápido

```bash
# 1. Clonar el repositorio y entrar al directorio
git clone https://github.com/ingelectronicadj/voiceover-a11y-auditor.git
cd voiceover-a11y-auditor

# 2. Verificar versión y ejecutar el autodiagnóstico interno (no requiere simulador)
python3 voiceover_audit.py --version
python3 voiceover_audit.py --self-test

# 2. Listar todos los simuladores iOS disponibles en Xcode
python3 voiceover_audit.py --list-sims

# 3. Instalar un archivo .ipa (o .app) y auditarlo en el simulador más reciente
python3 voiceover_audit.py --ipa ~/Downloads/mi_app.ipa --device "iPhone 18 Pro" --out reportes/mi_vista

# 4. Ejecutar prueba comparativa entre el iPhone más actual y una versión anterior de iOS / viewport
python3 voiceover_audit.py --devices "iPhone 18 Pro,iPhone XR" --view-title "Welcome - Multi-Viewport" --out reportes/comparativa_viewport --pack
```

---

## Opciones de línea de comandos (CLI)

| Opción | Descripción | Valor por defecto |
|---|---|---|
| `--version` | Muestra la versión instalada y termina | - |
| `--self-test` | Valida sin simulador los 86 criterios WCAG 2.2, las 16 reglas `VO-*` y el generador HTML | - |
| `--list-sims` | Lista todos los simuladores iOS disponibles en Xcode e indica cuáles están encendidos (`[BOOTED]`) | - |
| `--list-apps` | Lista todas las apps de usuario instaladas en el simulador activo | - |
| `--ipa IPA_OR_APP` | Adapta e instala un archivo `.ipa` (o `.app`) en el simulador objetivo | - |
| `--profile NAME`, `-p` | Carga el perfil `profiles/<NAME>.local.json` (ej. `--profile app_staging`) | Auto |
| `--pkg BUNDLE_ID` | `bundleIdentifier` iOS de la aplicación bajo prueba | Auto / Config |
| `--locale BCP47` | Configura el idioma y región del simulador iOS antes de auditar (ej. `es-AR`, `en-US`) | Según perfil |
| `--device SIM` | UDID o nombre del simulador iOS objetivo (ej. `"iPhone 18 Pro"`, `"iPhone XR"`, `"booted"`) | `booted` |
| `--devices LIST` | Lista de simuladores separados por coma para pruebas comparativas multi-viewport | - |
| `--view VIEW_ID` | Ejecuta el perfil declarativo de una vista (`config['views'][VIEW_ID]`) o `all` | - |
| `--view-title TITLE` | Título descriptivo de la vista para el `<title>` y el banner de cabecera del reporte | Auto (`<h1>`) |
| `--steps N` | Número máximo de pasos en barrido automático | `60` |
| `--delay SECS` | Espera entre pasos para permitir que el foco actualice su resaltado | `0.75` |
| `--login` / `--refresh` | Ejecuta flujo de autenticación pre-auditoría si está configurado en el perfil | `False` |
| `--keep-alive SECS` | Intervalo de renovación de sesión en segundo plano (`0` para desactivar) | Según config |
| `--test-modals` | Abre y cierra modales/drawers detectados para validar `Focus Return` (`VO-FOCUS-001`) | `False` |
| `--compare IOS_DIR ANDROID_DIR` | Genera un reporte HTML comparativo lado a lado (`VoiceOver` vs `TalkBack`) para una vista o suite completa | - |
| `--pack [ZIP_FILE]` | Genera portada maestra `index.html` y empaqueta la suite de reportes en un archivo `.zip` | - |
| `--rebuild DIR` | Reconstruye `report.html` a partir de `steps.json` y las capturas de `DIR/img/` | - |

---

## Arquitectura del proyecto

```text
.
├── voiceover_audit.py         # Entrypoint CLI, orquestador multi-dispositivo y modo --self-test
├── vo_bridge.swift            # Puente nativo Xcode (XDMDeviceManager + AXAudit + WebInspector)
├── vo_ocr.swift               # OCR nativo sobre Vision.framework y detector de recuadro de foco
├── config.example.json        # Plantilla de configuración (copiar a profiles/<app>.local.json)
├── profiles/                  # Perfiles locales por app/entorno (*.local.json ignorados en git)
├── reportes/                  # Salidas organizadas por aplicación/proyecto (ignoradas en git)
├── CHANGELOG.md               # Historial de cambios por versión
├── vo_audit/
│   ├── __init__.py            # Versión del paquete (VERSION = "0.2.0")
│   ├── config.py              # Carga de configuración jerárquica y mapeo de traits UIAccessibility
│   ├── ios_client.py          # Cliente xcrun simctl, parcheo Mach-O de .ipa y ejecución de vo_bridge
│   ├── rwi.py                 # Inspector WKWebView DOM / ARIA e IndexedDB vía Safari WebInspector
│   ├── vision.py              # Correlación geométrica de nodos y OCR de respaldo
│   ├── wcag_catalog.py        # Taxonomía oficial WCAG 2.2 (86 criterios) y catálogo de 16 reglas VO-*
│   ├── rules.py               # Motor de heurísticas por nodo, texto, secuencia, encabezados y omitidos
│   ├── report.py              # Generador de steps.json, reporte HTML interactivo e índice/ZIP de suite
│   └── sso.py                 # Hook opcional de autenticación pre-prueba y keep-alive en background
└── docs/
    ├── architecture.md                # Arquitectura interna, puente AXAudit, parcheo de .ipa y RWI
    ├── wcag-rules-catalog.md          # Catálogo detallado de las 16 reglas VO-* y criterios WCAG 2.2
    ├── configuration-and-profiles.md  # Configuración multi-dispositivo, WKWebView, i18n y Jira
    └── troubleshooting-voiceover-ios.md # Guía de resolución de problemas en iOS Simulator y Xcode
```

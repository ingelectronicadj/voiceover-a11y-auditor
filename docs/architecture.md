# Arquitectura y funcionamiento interno

Este documento describe las decisiones técnicas de diseño de **VoiceOver Audit** para lograr barridos lineales deterministas, captura exacta de voz e inspección de componentes nativos (`UIKit` / `SwiftUI`) e híbridos (`WKWebView`) sobre iOS Simulator y Xcode.

---

## 1. Desafíos de automatizar VoiceOver en iOS

1. **Los archivos `.ipa` de QA están compilados para `iphoneos` (dispositivo físico)**:
   En entornos bancarios y de QA, los artefactos distribuidos suelen ser paquetes `.ipa` firmados para dispositivos físicos (`PLATFORM_IOS`). Por defecto, `xcrun simctl install` rechaza instalar binarios cuya cabecera Mach-O `LC_BUILD_VERSION` indique `platform IOS` (2) en lugar de `IOSSIMULATOR` (7).
2. **Lectura exacta de la frase anunciada por VoiceOver y metadatos `UIAccessibility`**:
   Depender únicamente de OCR sobre pantalla es sensible a fondos animados o vídeos en bucle. Es necesario obtener directamente del motor de accesibilidad de iOS (`axauditd`) tanto la cadena hablada (`spokenDescription` / `captionText`) como los atributos `accessibilityLabel`, `accessibilityTraits` y `accessibilityIdentifier`.
3. **Inspección de `WKWebView` sin Chrome DevTools Protocol**:
   A diferencia de Android (donde el WebView expone un socket Chromium CDP), en iOS los microfrontends híbridos corren sobre WebKit (`WKWebView`) y se inspeccionan a través del demonio `webinspectord` con el protocolo multiplexado de Safari Remote Web Inspector.

---

## 2. Cómo los resuelve VoiceOver Audit

### A. Parcheo Mach-O automático de `.ipa` en Apple Silicon (`vo_audit/ios_client.py`)

En Macs con Apple Silicon (`arm64`), el conjunto de instrucciones de un binario `iphoneos` (`arm64`) es idéntico al del simulador (`arm64`). `IosClient.install_app_or_ipa()`:

1. Desempaqueta el `.ipa` en un directorio temporal y elimina `embedded.mobileprovision`.
2. Actualiza `CFBundleSupportedPlatforms` a `["iPhoneSimulator"]` y `DTPlatformName` a `"iphonesimulator"` en todos los `Info.plist`.
3. Ejecuta `vtool -arch arm64 -set-build-version iossim <minos> 26.5 -replace` sobre el ejecutable principal y todos los binarios de `Frameworks/*.framework`.
4. Re-firma ad-hoc el paquete completo (`codesign -f -s - --deep`) y lo instala en el simulador activo con `xcrun simctl install`.

### B. Puente nativo con `AccessibilityAuditDeviceManager` (`vo_bridge.swift`)

`vo_bridge.swift` carga dinámicamente `CoreSimulator.framework`, `DTXConnectionServices.framework` y `AccessibilityAuditDeviceManager.framework`:

- Conecta con `XDMDeviceSIM` mediante `XDMDeviceManager.sharedManager()`.
- Activa el resaltado de foco accesible (`inspectorEnable:true`, `setInspectorShowVisuals:true`, `enableHighlight:true`), que dibuja el recuadro verde oficial (`RGB 160, 190, 168`) sobre el elemento enfocado en el simulador.
- Posiciona deterministamente el cursor en el primer elemento accesible de la pantalla (`direction = 5`) y avanza paso a paso (`direction = 4`) hasta detectar el fin de la vista o ciclo completo.
- En cada paso recibe `AXAuditInspectorFocus` con `captionText`, `spokenDescription` y consulta las propiedades `XRCInspectorProperty` (`Label`, `Value`, `TraitsHumanReadable`, `Identifier`, `Hint`, `ElementClassName`).

### C. Inspección DOM / ARIA e `IndexedDB` en `WKWebView` (`vo_audit/rwi.py`)

Cuando la pantalla contiene un `WKWebView`:

1. `vo_bridge rwi-eval` carga `WebInspector.framework` (`RWIManager.sharedManager()`), localiza el simulador por `UDID` y abre un canal `RWIChannel` hacia la página `RWIDebuggable` activa.
2. Envía `Target.sendMessageToTarget` encapsulando `Runtime.evaluate` (`awaitPromise: true`) con `DOM_EXTRACT_JS`.
3. Extrae todos los nodos semánticos, atributos ARIA, círculos SVG de gráficas y el diccionario de traducciones en `IndexedDB`.

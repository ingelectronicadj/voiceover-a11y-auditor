# Guía de troubleshooting: VoiceOver en iOS Simulator y Xcode

Esta guía reúne las soluciones a los problemas más frecuentes al auditar accesibilidad en iOS Simulator con Xcode.

---

## 1. VoiceOver anuncia traits en inglés (`Button`, `Header`, `Link`) en una app en español

- **Causa**: el idioma del simulador iOS está en `en-US` o `en`. El servidor de accesibilidad del simulador toma el idioma de los traits (`Botón`, `Encabezado`, `Enlace`, `Atenuado`) de `AppleLanguages` y `AppleLocale`.
- **Solución**: pasa `--locale es-AR` en la línea de comandos o define `"locale": "es-AR"` en tu perfil JSON.

---

## 2. Un archivo `.ipa` falla al instalarse manualmente con `xcrun simctl install`

- **Causa**: los archivos `.ipa` descargados de repositorios de QA o Firebase suelen estar compilados para dispositivo físico (`platform IOS` en su comando Mach-O `LC_BUILD_VERSION`).
- **Solución**: usa siempre `--ipa <ruta.ipa>` en `voiceover_audit.py`. `IosClient.install_app_or_ipa()` convierte automáticamente las cabeceras Mach-O de la aplicación y de todos sus frameworks a `IOSSIMULATOR` con `vtool` y los re-firma con `codesign`.

---

## 3. El recuadro verde de foco queda visible en el simulador tras interrumpir una corrida

- **Solución**: ejecuta ` ./vo_bridge reset-overlay --udid booted` para apagar inmediatamente `setInspectorShowVisuals` y `enableHighlight` en el simulador.

# Configuración y perfiles de aplicación

**VoiceOver Audit** funciona sin configuración previa sobre cualquier aplicación iOS instalada en el simulador, y permite definir perfiles por aplicación o entorno en `profiles/<nombre>.local.json` (ignorados en git).

---

## 1. Auditoría rápida de un archivo `.ipa` o `.app`

```bash
# 1. Ver qué simuladores están disponibles en Xcode
python3 voiceover_audit.py --list-sims

# 2. Instalar un archivo .ipa (lo adapta automáticamente para Simulator) y auditarlo
python3 voiceover_audit.py --ipa ~/Downloads/mi_app.ipa --device "iPhone 18 Pro" --out reportes/welcome

# 3. Comparar el mismo flujo en dos dispositivos/viewports distintos (ej. iPhone 18 Pro iOS 27.0 vs iPhone XR iOS 18.6)
python3 voiceover_audit.py --devices "iPhone 18 Pro,iPhone XR" --view-title "Welcome" --out reportes/comparativa --pack
```

---

## 2. Estructura de `profiles/<nombre>.local.json`

```json
{
  "device": "iPhone 18 Pro",
  "device_matrix": [
    "iPhone 18 Pro",
    "iPhone XR"
  ],
  "locale": "es-AR",
  "app_pkg": "com.example.myapp",
  "keep_alive_sec": 85,
  "login_url": "https://...",
  "sso_url": "https://...",
  "sso_token": "1234",
  "login_body": {},
  "sso_body": {},
  "jira_base_url": "https://...",
  "jira_bugs": [],
  "views": {
    "welcome": {
      "title": "Welcome Screen (Login pre-autenticación)",
      "short_title": "Welcome",
      "scope_tag": "Welcome",
      "steps": 15,
      "out": "reportes/app_staging/00_welcome"
    }
  }
}
```

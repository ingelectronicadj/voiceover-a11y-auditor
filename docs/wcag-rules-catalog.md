# Catálogo de reglas `VO-*` y taxonomía WCAG 2.2

**VoiceOver Audit** incluye los **86 criterios de conformidad de WCAG 2.2 (niveles A, AA y AAA)** en `vo_audit/wcag_catalog.py` y evalúa automáticamente **16 reglas especializadas para iOS VoiceOver (`VO-*`)** en `vo_audit/rules.py`.

---

## Resumen de las 16 reglas automatizadas (`VO-*`)

| ID regla | Criterio WCAG 2.2 | Nivel | Severidad | Qué detecta |
|---|---|---|---|---|
| `VO-I18N-001` | `3.1.2` Idioma de las partes / `2.4.6` | AA | Alta | Keys de traducción crudas sin resolver (`a11y_*`, `i18n_*`, `msg_*`), textos en inglés dentro de vistas en español (o viceversa), placeholders sin interpolar (`{variable}`) o errores de tilde/voseo. |
| `VO-LINK-001` | `2.4.4` Propósito de los enlaces | A | Alta | Enlaces sin texto de destino (anuncian solo `«(Abrir una nueva ventana). Enlace»`) o que duplican su etiqueta (`«Saber más. Saber más...»`) por autorreferencia en `aria-labelledby`. |
| `VO-SKEL-001` | `4.1.3` Mensajes de estado / `2.4.3` | AA | Alta | Pantallas o drawers en estado de carga con *skeletons* que no anuncian `«Cargando {título}»` o dejan nodos `role="status"` vacíos (`«status»`). |
| `VO-CHART-001` | `2.4.1` Evitar bloques | A | Alta | Gráficas interactivas (`<svg>`) cuyos puntos individuales (`<circle>`) obligan al usuario de VoiceOver a hacer decenas o cientos de swipes para cruzar la gráfica. |
| `VO-FOCUS-001` | `2.4.3` Orden del foco | A | Alta | Pérdida de retorno de foco (*Focus Return*): al cerrar un diálogo modal, sheet o drawer, el foco de VoiceOver no regresa al botón disparador que lo abrió. |
| `VO-CURR-001` | `1.3.1` Información y relaciones | A | Alta | Importes monetarios en pesos u otra moneda local que usan el símbolo `$` sin desambiguar en `accessibilityLabel` / `aria-label`, haciendo que el TTS de VoiceOver anuncie `«dólares»`. |
| `VO-UNREACH-001` | `1.3.1` Información y relaciones / `2.1.1` | A | Alta | Elementos o etiquetas semánticas presentes en el DOM activo que son omitidos por VoiceOver durante el barrido lineal. |
| `VO-HEAD-002` | `1.3.1` Información y relaciones / `2.4.6` | A | Media | Jerarquía de encabezados (`H1-H6` / `.isHeader`) con saltos de nivel (`H1 -> H3` sin `H2`), ausencia de `H1` principal o encabezados ocultos con párrafos extensos (`> 120` caracteres). |
| `VO-NAME-001` | `4.1.2` Nombre, función, valor | A | Alta | Controles interactivos (`Button`, `Link`) que carecen de nombre accesible (`accessibilityLabel` o `aria-label`). |
| `VO-IMG-001` | `1.1.1` Contenido no textual | A | Alta | Imágenes, iconos o gráficos sin alternativa textual o decorativos no ocultos que disparan reconocimiento de VoiceOver. |
| `VO-MERGE-001` | `1.3.2` Secuencia significativa | A | Media | Un único paso de foco concatena `>= 18` palabras o duplica párrafos largos dentro de un encabezado oculto. |
| `VO-LABEL-001` | `2.5.3` Etiqueta en el nombre | A | Media | El `accessibilityLabel` / `aria-label` no contiene el texto visible en pantalla del botón o control. |
| `VO-TARGET-001` | `2.5.8` Tamaño del objetivo (mínimo) | AA | Media | Controles interactivos con área táctil inferior a `44x44 pt` (Apple HIG / WCAG 2.5.8). |
| `VO-STATUS-001` | `4.1.3` Mensajes de estado | AA | Media | Mensajes de error de sección (`Tuvimos un problema`, `No es posible recuperar...`) o contenedores `role="status"` vacíos expuestos en el barrido lineal. |
| `VO-HEAD-001` | `2.4.6` Encabezados y etiquetas | AA | Baja | La etiqueta accesible incluye manualmente el nombre del rol (`botón`, `icono`, `imagen`), provocando anuncios redundantes con el trait de VoiceOver. |
| `VO-LANG-001` | `3.1.2` Idioma de las partes | AA | Baja | VoiceOver mezcla traits del sistema en inglés (`Button`, `Header`, `Link`, `Dimmed`) con interfaz en español. |

# Content Studio IA (versión 0.7)

Esta es la carpeta del **programa** (el motor). Las usuarias no trabajan aquí: cada una tiene su carpeta
«Content Studio ediciones» en el Escritorio y edita hablando con Claude mediante la skill **content-studio**.
Habla siempre en español, con palabras sencillas: quien lo usa no es programadora. No prometas funciones que
no estén implementadas. Los vídeos y datos de la usuaria no salen de su ordenador.

## Si alguien pide editar un vídeo aquí
Usa la skill **content-studio**. Si no está disponible, no está instalada: sigue el paso 6 de `INSTALAR.md`
(crea su carpeta e instala la skill) y pide que reinicie Claude. Nunca le abras el menú de terminal.

## Si te piden instalar, actualizar o comprobar
Sigue `INSTALAR.md` paso a paso (permisos en el chat, nunca contraseñas). Para comprobar sin instalar nada:
- Windows: `powershell -NoProfile -ExecutionPolicy Bypass -File instalador\instalar.ps1 -SoloComprobar -Prueba`
- Mac: `bash instalador/instalar_mac.sh --solo-comprobar --prueba`

## Para quien mantiene el programa
Python 3.12+ y FFmpeg 7+; faster-whisper y Pillow en `.venv` (content_studio.py se relanza solo con `.venv`).

**Skill.** `skill/SKILL.md` es una plantilla: `content_studio.py --carpeta "<su carpeta>" preparar` la copia a
`~/.claude/skills/content-studio/SKILL.md` sustituyendo `{{PYTHON}}`, `{{MOTOR}}`, `{{CARPETA}}` y `{{VERSION}}`,
y crea en su carpeta `entrada/`, `salida/`, `marca/`, `REFERENCIAS/` y un `CLAUDE.md`. Si cambias la skill,
hay que volver a ejecutar `preparar` (lo hace el instalador en cada actualización).

**Carpeta de trabajo.** `--carpeta <ruta>` (en cualquier posición; o la variable `CONTENT_STUDIO_CARPETA`)
hace que entrada/, salida/, marca/ y REFERENCIAS/ se lean de esa carpeta. Sin ella, se usa la del programa
(como en la 0.6).

**Órdenes sin preguntas** (terminan en `RESULTADO: {json}`): `estado`, `marca ver|guardar|cambiar|activar|muestra`,
`editar <vídeos|todos> [--sin-cortes] [--sin-subtitulos] [--estilo X] [--efectos a,b] [--destacar p]`,
`preparar`. También: `cortar VIDEO [--solo-proponer]`, `subtitular VIDEO [--corregir mal=bien] [--marca X.json]`,
`referencias [--carpeta X] [--no-guardar]`. Sin argumentos abre el menú antiguo de terminal.

- content_studio.py: órdenes, cortar silencios (umbral automático por RMS cada 20 ms, cortes a fotograma
  entero con trim/atrim+concat), unir clips, paso a vertical (recortar/rellenar).
- marca.py: ficha por usuaria en <carpeta>/marca/perfiles/<slug>.json, activa en marca/activa.txt. Las fichas
  nuevas parten de `plantillas/estilo_base.json` (estilo de la casa). estilo_subtitulos() y efectos() la traducen.
- subtitulos.py: transcripción local, grupos de 1-3 palabras, destacadas (con letra y cursiva propias), ASS
  1080x1920, SRT, grabado con libass.
- efectos.py: zoom, destellos en cortes, pegatinas emoji (lista en <carpeta>/marca/pegatinas.json) o PNG
  (recursos/pegatinas).
- referencias.py: analiza REFERENCIAS (colores y ritmo).
- instalador/: instalar.ps1, instalar_mac.sh, comprobar.py y prueba_exportacion.py (vídeo sintético).
Carpetas de usuaria (nunca van al repositorio): entrada/, salida/, marca/, REFERENCIAS/, .venv/.

Todavía NO: música/sonido, detección de cara, edición semántica, títulos en un momento concreto, Mac Intel.

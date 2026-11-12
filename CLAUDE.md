# Content Studio IA (versión 0.6)
Programa propio de edición de vídeos verticales. Responde siempre en español, con palabras sencillas: quien
lo usa no es programadora. No prometas funciones que no estén implementadas. Los vídeos y datos de la
usuaria no salen de su ordenador.

## Si te piden instalar, actualizar o comprobar
Sigue `INSTALAR.md` paso a paso (permisos en el chat, nunca contraseñas). Para comprobar sin instalar nada:
- Windows: `powershell -NoProfile -ExecutionPolicy Bypass -File instalador\instalar.ps1 -SoloComprobar -Prueba`
- Mac: `bash instalador/instalar_mac.sh --solo-comprobar --prueba`

## Módulos (Python 3.12+ y FFmpeg 7+; faster-whisper y Pillow en .venv; content_studio.py se relanza solo con .venv)
- content_studio.py: menú, cortar silencios (umbral automático por RMS cada 20 ms, cortes a fotograma
  entero con trim/atrim+concat), unir clips, paso a vertical (recortar/rellenar), flujo de edición.
  En Mac añade al PATH el ffmpeg-full de Homebrew (el «ffmpeg» normal no trae libass).
- marca.py: ficha por usuaria en marca/perfiles/<slug>.json, activa en marca/activa.txt. Asistente de
  13 preguntas, colores por nombre o hex, comprobación de letras instaladas. estilo_subtitulos() y
  efectos() traducen la ficha.
- subtitulos.py: transcripción local (audio decodificado por FFmpeg -> numpy), grupos de 1-3 palabras,
  destacadas (fijas de la ficha + extra + automáticas), ASS 1080x1920 (color o marcador), SRT, grabado
  con libass + efectos.
- efectos.py: zoompan (salto de zoom en tramos alternos + acercamiento en destacadas), eq brightness
  (destello en cortes), pegatinas emoji (Pillow + fuente de emojis del sistema) o PNG propios.
- referencias.py: analiza REFERENCIAS (colores con quantize de Pillow, ritmo con select scene>0.30) y
  solo cambia la ficha con aprobación.
Carpetas de la usuaria (nunca van al repositorio): entrada/, salida/, marca/, REFERENCIAS/, .venv/.

## Uso sin menú
`content_studio.py cortar VIDEO [--solo-proponer]` · `subtitular VIDEO [--marca <perfil>.json]` ·
`referencias [--carpeta X] [--no-guardar]`

## Instalación y pruebas
- instalador/instalar.ps1 (Windows, winget) e instalador/instalar_mac.sh (Mac, Homebrew): preguntan en la
  ventana con doble clic; desde Claude, modo sin preguntas con permisos explícitos. Terminan con
  «RESULTADO: ...» y un código de salida (tabla en INSTALAR.md).
- instalador/comprobar.py: diagnóstico. instalador/prueba_exportacion.py: vídeo sintético por el flujo
  completo con plantillas/marca_ejemplo.json (sin voz real: las palabras se le dan escritas).
- instalador/requisitos.txt: versiones fijadas. Tipografías OFL en recursos/fuentes (libass las lee con fontsdir).

Todavía NO: OCR de letras en referencias, música/sonido, detección de cara, edición semántica, Mac Intel.

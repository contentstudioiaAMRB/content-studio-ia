#!/bin/bash
# Content Studio IA - instalador para Mac (v0.6)
# Comprueba lo que hace falta y, si falta algo, explica qué es y pide permiso antes de instalarlo.
# Todo lo de Python va dentro de la carpeta del programa (.venv).
#
# Dos formas de usarlo:
#  - Con doble clic en «1 - Instalar (Mac).command»: pregunta en la ventana (s/n).
#  - Desde Claude Code (sin ventana para contestar): --no-interactivo y los permisos que la usuaria
#    haya dado en el chat: --instalar-python --instalar-ffmpeg --descargar-modelo.
#    Sin esas opciones no se instala ni se descarga nada grande.
# Homebrew pide la contraseña del Mac: eso lo hace siempre la usuaria en la app Terminal, nunca Claude.
# Al final escribe una línea «RESULTADO: ...» que Claude puede leer.
# Compatible con el bash 3.2 que trae macOS.
set -u

NO_INTERACTIVO=0; P_PYTHON=0; P_FFMPEG=0; P_MODELO=0; PRUEBA=0; SOLO_COMPROBAR=0
for a in "$@"; do
  case "$a" in
    --no-interactivo) NO_INTERACTIVO=1 ;;
    --instalar-python) P_PYTHON=1 ;;
    --instalar-ffmpeg) P_FFMPEG=1 ;;
    --descargar-modelo) P_MODELO=1 ;;
    --prueba) PRUEBA=1 ;;
    --solo-comprobar) SOLO_COMPROBAR=1 ;;
    *) echo "Opción desconocida: $a"; exit 2 ;;
  esac
done

RAIZ="$(cd "$(dirname "$0")/.." && pwd)"
cd "$RAIZ" || exit 1
VENV_PY="$RAIZ/.venv/bin/python"

titulo() { echo; echo "== $1"; }
bien() { echo "   OK  $1"; }
mal() { echo "   !!  $1"; }
resultado() { echo; echo "RESULTADO: $2"; exit "$1"; }
# permiso "pregunta" <permiso_dado 0|1>
permiso() {
  if [ "$2" = "1" ]; then echo "$1 -> sí (permiso dado)"; return 0; fi
  if [ "$NO_INTERACTIVO" = "1" ]; then echo "$1 -> no (sin permiso)"; return 1; fi
  read -r -p "$1 (s/n) " r
  [[ "$r" =~ ^([sS]|si|sí|Si|Sí|y|Y)$ ]]
}

cargar_brew() {
  command -v brew >/dev/null 2>&1 && return 0
  for b in /opt/homebrew/bin/brew /usr/local/bin/brew; do
    [ -x "$b" ] && eval "$("$b" shellenv)" && return 0
  done
  return 1
}

# El FFmpeg completo de Homebrew (ffmpeg-full, con libass para los subtítulos) no se enlaza en el PATH:
# se añade aquí y también lo añade content_studio.py al arrancar.
poner_ffmpeg_full() {
  for d in /opt/homebrew/opt/ffmpeg-full/bin /usr/local/opt/ffmpeg-full/bin; do
    [ -x "$d/ffmpeg" ] && export PATH="$d:$PATH" && return 0
  done
  return 1
}

version_ffmpeg() { ffmpeg -version 2>/dev/null | head -1 | sed -nE 's/^ffmpeg version n?([0-9]+).*/\1/p'; }
ffmpeg_con_subtitulos() { ffmpeg -hide_banner -filters 2>/dev/null | grep -qE '[[:space:]]subtitles[[:space:]]'; }

comprobar() {
  [ -x "$VENV_PY" ] || { mal "Todavía no está instalado (falta la carpeta .venv)."; resultado 13 "FALTA instalar las bibliotecas (ejecuta el instalador)"; }
  "$VENV_PY" instalador/comprobar.py || resultado 14 "FALTA algo (mira las líneas FALTA de la comprobación)"
  if [ "$PRUEBA" = "1" ]; then
    "$VENV_PY" instalador/prueba_exportacion.py || resultado 15 "FALLA la prueba de exportación"
    resultado 0 "OK (comprobación y prueba de exportación superadas)"
  fi
  resultado 0 "OK (comprobación superada)"
}

echo
echo "CONTENT STUDIO IA 0.6 - INSTALACIÓN EN MAC"
echo "Carpeta del programa: $RAIZ"
cargar_brew
poner_ffmpeg_full

[ "$SOLO_COMPROBAR" = "1" ] && comprobar

# ---------------------------------------------------------------- 0. Este Mac
titulo "0/5  Este Mac"
ARM="$(sysctl -n hw.optional.arm64 2>/dev/null || echo 0)"
MACOS="$(sw_vers -productVersion 2>/dev/null || echo 0)"
MACOS_MAYOR="${MACOS%%.*}"
if [ "$ARM" != "1" ]; then
  mal "Este Mac tiene procesador Intel. El reconocimiento de voz (onnxruntime) solo funciona en Mac con chip Apple (M1 o posterior)."
  resultado 21 "NO COMPATIBLE: hace falta un Mac con chip Apple (M1 o posterior)"
fi
if [ "${MACOS_MAYOR:-0}" -lt 14 ] 2>/dev/null; then
  mal "Tienes macOS $MACOS. Hace falta macOS 14 (Sonoma) o posterior: actualízalo en Ajustes del Sistema > General > Actualización de software."
  resultado 22 "NO COMPATIBLE: hace falta macOS 14 (Sonoma) o posterior (ahora $MACOS)"
fi
bien "Mac con chip Apple y macOS $MACOS."

# Homebrew (instalador de programas gratuito para Mac), solo si hace falta
asegurar_brew() {
  cargar_brew && return 0
  mal "Para instalar lo que falta uso Homebrew (gratuito, https://brew.sh), y todavía no está en este Mac."
  if [ "$NO_INTERACTIVO" = "1" ]; then
    echo "   Homebrew pide la contraseña del Mac, así que lo tiene que instalar la usuaria:"
    echo "   abre la app Terminal, pega esta línea, pulsa Enter y escribe tu contraseña del Mac cuando la pida:"
    echo '   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'
    resultado 20 "FALTA Homebrew (lo instala la usuaria en Terminal; después vuelve a ejecutar el instalador)"
  fi
  if permiso "   ¿Instalo Homebrew con su instalador oficial? (pedirá tu contraseña del Mac)" 0; then
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    cargar_brew && return 0
  fi
  return 1
}

# ---------------------------------------------------------------- 1. Python
titulo "1/5  Python 3.12 o superior"
buscar_python() {
  PY=""
  for c in python3.13 python3.12 python3 \
           /opt/homebrew/bin/python3.12 /opt/homebrew/bin/python3.13 \
           /Library/Frameworks/Python.framework/Versions/3.12/bin/python3 \
           /Library/Frameworks/Python.framework/Versions/3.13/bin/python3; do
    if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)' 2>/dev/null; then
      PY="$(command -v "$c")"; return 0
    fi
  done
  return 1
}
if buscar_python; then
  bien "Python encontrado: $("$PY" --version)"
else
  mal "No he encontrado Python 3.12 o superior (el que trae el Mac es más antiguo)."
  asegurar_brew || resultado 20 "FALTA Homebrew para instalar Python"
  if permiso "   ¿Instalo Python 3.12 con Homebrew (gratuito)?" "$P_PYTHON"; then
    brew install python@3.12
  fi
  buscar_python || resultado 10 "FALTA Python 3.12 (pide permiso para instalarlo con --instalar-python)"
  bien "Python instalado: $("$PY" --version)"
fi

# ---------------------------------------------------------------- 2. FFmpeg
titulo "2/5  FFmpeg 7 o superior, con subtítulos (libass)"
FFV="$(version_ffmpeg)"; FFV="${FFV:-0}"
if [ "$FFV" -ge 7 ] && ffmpeg_con_subtitulos; then
  bien "FFmpeg $FFV encontrado, con subtítulos."
else
  if [ "$FFV" -ge 7 ]; then
    mal "Tienes FFmpeg $FFV, pero sin el filtro de subtítulos (el «ffmpeg» normal de Homebrew ya no lo trae)."
  else
    mal "Hace falta FFmpeg 7 o superior (ahora: $([ "$FFV" = 0 ] && echo ninguno || echo "$FFV"))."
  fi
  asegurar_brew || resultado 20 "FALTA Homebrew para instalar FFmpeg"
  echo "   Instalo «ffmpeg-full» de Homebrew (gratuito; no sustituye a otro FFmpeg que tengas)."
  if permiso "   ¿Instalo FFmpeg completo con Homebrew?" "$P_FFMPEG"; then
    brew install ffmpeg-full
    poner_ffmpeg_full
  fi
  FFV="$(version_ffmpeg)"; FFV="${FFV:-0}"
  if [ "$FFV" -lt 7 ] || ! ffmpeg_con_subtitulos; then
    resultado 11 "FALTA FFmpeg 7+ con subtítulos (pide permiso para instalarlo con --instalar-ffmpeg)"
  fi
  bien "FFmpeg $FFV listo, con subtítulos."
fi

# ---------------------------------------------------------------- 3. Bibliotecas
titulo "3/5  Bibliotecas del programa (unos 300 MB, dentro de la carpeta .venv)"
if [ -x "$VENV_PY" ] && ! "$VENV_PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)' 2>/dev/null; then
  mal "La carpeta .venv era de un Python antiguo: la vuelvo a crear."
  rm -rf "$RAIZ/.venv"
fi
[ -x "$VENV_PY" ] || "$PY" -m venv .venv
"$VENV_PY" -m pip install --disable-pip-version-check --quiet -r instalador/requisitos.txt \
  || { mal "No se pudieron instalar las bibliotecas. ¿Hay conexión a internet?"; resultado 12 "FALLA la instalación de bibliotecas (¿internet?)"; }
bien "Bibliotecas instaladas."

# ---------------------------------------------------------------- 4. Modelo de voz
titulo "4/5  Modelo de voz (unos 1,6 GB, una sola vez; si no, se baja la primera vez que pongas subtítulos)"
if permiso "   ¿Lo descargo ahora?" "$P_MODELO"; then
  "$VENV_PY" -c "from faster_whisper import WhisperModel; WhisperModel('large-v3-turbo', device='cpu', compute_type='int8'); print('modelo listo')" \
    || mal "No se pudo descargar el modelo; se intentará la primera vez que pongas subtítulos."
fi

# ---------------------------------------------------------------- 5. Acceso
titulo "5/5  Preparar el acceso"
chmod +x "$RAIZ/Abrir Content Studio IA.command" "$RAIZ/1 - Instalar (Mac).command" 2>/dev/null
bien "Abre el programa con «Abrir Content Studio IA.command» (clic derecho > Abrir la primera vez)."

comprobar

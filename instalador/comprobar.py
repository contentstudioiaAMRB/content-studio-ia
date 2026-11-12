"""Comprueba que Content Studio IA tiene todo lo que necesita. No instala nada.
Uso: <python del programa> instalador/comprobar.py
Termina con «RESULTADO: OK» (código 0) o «RESULTADO: FALTA ...» (código 1).
"""
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

# Mac: el FFmpeg completo de Homebrew (con libass) no está en el PATH (igual que en content_studio.py)
if sys.platform == 'darwin':
    for _d in ('/opt/homebrew/opt/ffmpeg-full/bin', '/usr/local/opt/ffmpeg-full/bin'):
        if Path(_d, 'ffmpeg').exists():
            os.environ['PATH'] = _d + os.pathsep + os.environ.get('PATH', '')
            break

faltan = []


def ok(nombre, bien, detalle=''):
    if not bien:
        faltan.append(nombre)
    print(f"  [{'  OK  ' if bien else 'FALTA '}] {nombre}{(' — ' + detalle) if detalle else ''}")


def main():
    version = (ROOT / 'VERSION.txt').read_text(encoding='utf-8').strip() if (ROOT / 'VERSION.txt').exists() else ''
    print(f'\nCOMPROBACIÓN DE {version.upper() or "CONTENT STUDIO IA"}\n')
    ok('Python 3.12 o superior', sys.version_info >= (3, 12), sys.version.split()[0])
    ok('Entorno propio del programa (.venv)', Path(sys.prefix).resolve() == (ROOT / '.venv').resolve(),
       sys.prefix)
    ff, fp = shutil.which('ffmpeg'), shutil.which('ffprobe')
    ok('FFprobe', bool(fp), fp or 'no encontrado')
    if ff:
        v = subprocess.run([ff, '-version'], capture_output=True, text=True, errors='replace').stdout
        m = re.search(r'ffmpeg version n?(\d+)', v)
        mayor = int(m.group(1)) if m else 0
        ok('FFmpeg 7 o superior', mayor >= 7, (v.splitlines()[0][:70] if v else '') + f'  ({ff})')
        filtros = subprocess.run([ff, '-hide_banner', '-filters'], capture_output=True, text=True,
                                 errors='replace').stdout
        for f in ('subtitles', 'zoompan', 'silencedetect', 'astats', 'eq', 'overlay'):
            ok(f'FFmpeg: filtro {f}', re.search(rf'\s{f}\s', filtros) is not None)
        enc = subprocess.run([ff, '-hide_banner', '-encoders'], capture_output=True, text=True,
                             errors='replace').stdout
        ok('FFmpeg: códec H.264 (libx264)', 'libx264' in enc)
        ok('FFmpeg: códec AAC', re.search(r'\saac\s', enc) is not None)
    else:
        ok('FFmpeg', False, 'no encontrado')
    try:
        import faster_whisper
        ok('Reconocimiento de voz (faster-whisper)', True, faster_whisper.__version__)
    except Exception as e:
        ok('Reconocimiento de voz (faster-whisper)', False, str(e)[:80])
    try:
        import numpy
        ok('Cálculo (numpy)', True, numpy.__version__)
    except Exception as e:
        ok('Cálculo (numpy)', False, str(e)[:80])
    try:
        import PIL
        ok('Imágenes y pegatinas (Pillow)', True, PIL.__version__)
    except Exception as e:
        ok('Imágenes y pegatinas (Pillow)', False, str(e)[:80])
    fuentes = list((ROOT / 'recursos' / 'fuentes').glob('*.ttf'))
    ok('Tipografías incluidas', len(fuentes) >= 5, f'{len(fuentes)} archivos en recursos/fuentes')
    sys.path.insert(0, str(ROOT))
    try:
        import efectos
        ok('Letra de emojis para pegatinas', Path(efectos.FUENTE_EMOJI).exists(), efectos.FUENTE_EMOJI)
    except Exception as e:
        ok('Letra de emojis para pegatinas', False, str(e)[:80])
    cache = Path(os.environ.get('HF_HOME', Path.home() / '.cache' / 'huggingface')) / 'hub'
    modelo = any(cache.glob('models--*faster-whisper-large-v3-turbo*')) if cache.exists() else False
    print(f"  [ AVISO] Modelo de voz: {'ya descargado' if modelo else 'se descargará la primera vez (unos 1,6 GB)'}")
    print()
    if not faltan:
        print('TODO LISTO. Abre el programa con «Abrir Content Studio IA».')
        print('RESULTADO: OK')
        return 0
    print('Falta algo. Vuelve a ejecutar el instalador o pide ayuda.')
    print('RESULTADO: FALTA ' + '; '.join(faltan))
    return 1


if __name__ == '__main__':
    sys.exit(main())

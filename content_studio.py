"""Content Studio IA - versión 0.7.

Funciones:
  1. Ficha de marca (marca/perfil.json).
  2. Unir clips de entrada/ en un vertical 1080x1920.
  3. Cortar silencios: detecta silencios, propone cortes con sus segundos
     exactos, la usuaria aprueba o rechaza cada uno y se exporta un MP4
     vertical 1080x1920 con el audio sincronizado.
  4. Subtítulos automáticos (subtitulos.py): transcripción local con
     faster-whisper, subtítulos de 1-3 palabras con palabra destacada,
     grabados en el vídeo con el estilo de marca/estilo_subtitulos.json.

Los vídeos originales solo se leen; nunca se modifican ni se sobrescriben.
Todo lo que se exporta va a salida/ con un nombre nuevo cada vez.

Uso:
  python content_studio.py                          -> menú
  python content_studio.py cortar VIDEO [...]       -> sin menú (ver --help)
  python content_studio.py subtitular VIDEO [...]   -> sin menú (ver --help)
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

VERSION = '0.7'
ROOT = Path(__file__).resolve().parent

# Carpeta de trabajo de la usuaria (sus vídeos, su marca, sus editados). Por defecto, la del programa.
# Con «--carpeta <ruta>» en cualquier orden, cada chica trabaja en su propia carpeta.
if '--carpeta' in sys.argv[1:-1]:
    _i = sys.argv.index('--carpeta')
    os.environ['CONTENT_STUDIO_CARPETA'] = str(Path(sys.argv[_i + 1]).expanduser().resolve())
    del sys.argv[_i:_i + 2]
TRABAJO = Path(os.environ.get('CONTENT_STUDIO_CARPETA') or ROOT)
ENTRADA = TRABAJO / 'entrada'
SALIDA = TRABAJO / 'salida'
PROFILE = TRABAJO / 'marca' / 'perfil.json'
FUENTES = ROOT / 'recursos' / 'fuentes'
VENV_PY = ROOT / '.venv' / ('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')

# Mac: el FFmpeg completo de Homebrew (ffmpeg-full, con libass para los subtítulos) no está en el PATH.
if sys.platform == 'darwin':
    for _d in ('/opt/homebrew/opt/ffmpeg-full/bin', '/usr/local/opt/ffmpeg-full/bin'):
        if Path(_d, 'ffmpeg').exists():
            if _d not in os.environ.get('PATH', '').split(os.pathsep):
                os.environ['PATH'] = _d + os.pathsep + os.environ.get('PATH', '')
            break

# Si existe el entorno propio del programa (con faster-whisper), el programa se ejecuta con él.
# (Se compara la carpeta del entorno y no el ejecutable: en Mac el python del .venv es un enlace.)
if VENV_PY.exists() and Path(sys.prefix).resolve() != (ROOT / '.venv').resolve() \
        and __name__ == '__main__':
    sys.exit(subprocess.call([str(VENV_PY), str(Path(__file__).resolve()), *sys.argv[1:]]))
VIDEO_EXT = ('.mp4', '.mov', '.mkv', '.m4v')

ANCHO, ALTO, FPS = 1080, 1920, 30

# Valores recomendados para cortar silencios
UMBRAL_DB = None       # None = automático: se calcula con el ruido de fondo de cada vídeo
MIN_SILENCIO = 0.5     # segundos mínimos de silencio para proponer un corte
MARGEN = 0.15          # segundos que se respetan antes y después de la voz
MIN_CORTE = 0.2        # no se proponen cortes más cortos que esto

MODOS = {
    'recortar': 'Recortar para llenar la pantalla vertical (se pierde algo de los lados)',
    'rellenar': 'Conservar el vídeo completo con relleno difuminado arriba y abajo',
}

REFERENCIAS = TRABAJO / 'REFERENCIAS'


def preparar_carpetas():
    for d in ('recursos', 'recursos/fuentes', 'recursos/pegatinas'):
        (ROOT / d).mkdir(parents=True, exist_ok=True)
    for d in ('entrada', 'salida', 'marca'):
        (TRABAJO / d).mkdir(parents=True, exist_ok=True)
    # la antigua carpeta «referencias» pasa a llamarse REFERENCIAS (con su contenido)
    for p in TRABAJO.iterdir():
        if p.is_dir() and p.name.lower() == 'referencias' and p.name != 'REFERENCIAS':
            p.rename(TRABAJO / '__ref_tmp')
            (TRABAJO / '__ref_tmp').rename(REFERENCIAS)
    for sub in ('instagram', 'tiktok', 'pinterest', 'otras'):
        (REFERENCIAS / sub).mkdir(parents=True, exist_ok=True)
    leeme = REFERENCIAS / 'LEEME.txt'
    if not leeme.exists():
        leeme.write_text(
            'REFERENCIAS — pon aquí capturas (JPG/PNG) o vídeos (MP4/MOV) que te gusten:\n'
            '  instagram/  tiktok/  pinterest/  otras/\n'
            'Descárgalos desde la propia app (guardar/descargar) o haz una captura de pantalla.\n'
            'Puedes añadir al lado un .txt con el mismo nombre diciendo qué te gusta de cada uno.\n'
            'Esta versión todavía no analiza las referencias automáticamente: las guarda ordenadas\n'
            'para la siguiente etapa.\n', encoding='utf-8')


preparar_carpetas()

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass


# ---------------------------------------------------------------- utilidades

def ask(q, default=''):
    s = input(f'{q}' + (f' [{default}]' if default else '') + ': ').strip()
    return s or default


def run(cmd):
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       text=True, encoding='utf-8', errors='replace')
    if p.returncode:
        raise RuntimeError(p.stderr[-2500:])
    return p.stdout, p.stderr


def herramientas_ok():
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        print('Faltan FFmpeg/FFprobe. Instálalos desde su fuente oficial y vuelve a abrir el programa.')
        return False
    return True


def reloj(t):
    """12.4 -> '0:12,40'"""
    m, s = divmod(max(t, 0.0), 60)
    return f'{int(m)}:{s:05.2f}'.replace('.', ',')


def nombre_unico(base, ext='.mp4'):
    """salida/<base>_<fecha-hora>.mp4, sin pisar nunca un archivo existente."""
    sello = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    out = SALIDA / f'{base}_{sello}{ext}'
    n = 2
    while out.exists():
        out = SALIDA / f'{base}_{sello}_{n}{ext}'
        n += 1
    return out


def info_video(path):
    out, _ = run(['ffprobe', '-v', 'error', '-show_entries',
                  'format=duration,start_time:stream=codec_type,width,height',
                  '-of', 'json', str(path)])
    j = json.loads(out)
    fmt = j.get('format', {})
    streams = j.get('streams', [])
    return {
        'duracion': float(fmt.get('duration', 0) or 0),
        'inicio': float(fmt.get('start_time', 0) or 0),
        'audio': any(s.get('codec_type') == 'audio' for s in streams),
        'video': any(s.get('codec_type') == 'video' for s in streams),
    }


def filtro_vertical(modo):
    """Cadena de filtros que deja la imagen en 1080x1920 (el giro del móvil lo aplica FFmpeg solo)."""
    if modo == 'recortar':
        return (f'scale={ANCHO}:{ALTO}:force_original_aspect_ratio=increase,'
                f'crop={ANCHO}:{ALTO},setsar=1')
    # rellenar: el vídeo entero centrado sobre una copia ampliada y difuminada
    return (f'split=2[fondo][frente];'
            f'[fondo]scale={ANCHO}:{ALTO}:force_original_aspect_ratio=increase,'
            f'crop={ANCHO}:{ALTO},boxblur=30:2[fondo2];'
            f'[frente]scale={ANCHO}:{ALTO}:force_original_aspect_ratio=decrease[frente2];'
            f'[fondo2][frente2]overlay=(W-w)/2:(H-h)/2,setsar=1')


def elegir_modo():
    import marca
    p = marca.activo()
    if p:   # la marca ya lo dice: no se pregunta
        print(f'Paso a vertical según tu marca: {MODOS[p["vertical"]].split(" (")[0].lower()}.')
        return p['vertical']
    print('\n¿Cómo pasamos el vídeo a vertical?')
    claves = list(MODOS)
    for i, k in enumerate(claves, 1):
        print(f'  {i}. {MODOS[k]}')
    r = ask('Elige 1 o 2', '1')
    return claves[1] if r == '2' else claves[0]


# ---------------------------------------------------------------- marca

def perfil_activo(avisar=True):
    import marca
    p = marca.activo()
    if p is None and avisar:
        print('Todavía no hay ninguna marca. Se usarán los valores por defecto '
              '(configúrala en la opción 1 del menú).')
    return p


def brand():
    import marca
    actual = marca.activo()
    if actual and ask(f'Editar la marca de {actual["nombre"]}? (s = editarla, n = crear otra usuaria)',
                      's').lower() != 's':
        actual = None
    if actual is None and PROFILE.exists():   # ficha antigua de texto libre (versión 0.1)
        viejo = json.loads(PROFILE.read_text(encoding='utf-8'))
        actual = marca._fusionar(marca.PLANTILLA, {'nombre': viejo.get('nombre', ''),
                                                    'nicho': viejo.get('nichos', '')})
    marca.asistente(ask, actual)


def ver_marca():
    import marca
    p = marca.activo()
    print('\n' + (marca.resumen(p) if p else 'Primero crea tu marca (opción 1).'))


def cambiar_usuaria():
    import marca
    perfiles = marca.listar()
    if not perfiles:
        print('Todavía no hay ninguna marca guardada.')
        return
    for i, r in enumerate(perfiles, 1):
        print(f'  {i}. {marca.cargar(r)["nombre"]}')
    try:
        r = perfiles[int(ask('¿Quién va a editar? (número)', '1')) - 1]
    except (ValueError, IndexError):
        print('Número no válido.')
        return
    marca.activar(r)
    print(f'Ahora se usa la marca de {marca.cargar(r)["nombre"]}.')


# ---------------------------------------------------------------- unir clips

def listar_clips():
    return sorted(p for p in ENTRADA.iterdir() if p.is_file() and p.suffix.lower() in VIDEO_EXT)


def unir():
    if not herramientas_ok():
        return
    clips = listar_clips()
    if not clips:
        print('Coloca archivos MP4 o MOV en entrada/ y vuelve a intentar.')
        return
    print('\nCLIPS ENCONTRADOS:')
    for i, p in enumerate(clips, 1):
        print(f'{i}. {p.name} — {info_video(p)["duracion"]:.1f} segundos')
    if ask('¿Unirlos en este orden? (s/n)', 's').lower() != 's':
        return
    modo = elegir_modo()
    print('Uniendo los vídeos...')
    out = unir_clips(clips, modo)
    print('VIDEO CREADO:', out)


# ---------------------------------------------------------------- silencios

VENTANA = 0.02  # el volumen se mide cada 20 ms


def medir_volumen(path):
    """Volumen medio (RMS, en dB) del sonido cada 20 ms."""
    sr = 16000
    out, _ = run(['ffmpeg', '-hide_banner', '-nostats', '-i', str(path), '-map', '0:a:0', '-vn',
                  '-af', f'aresample={sr},asetnsamples={int(sr * VENTANA)},astats=metadata=1:reset=1,'
                         'ametadata=print:key=lavfi.astats.Overall.RMS_level:file=-',
                  '-f', 'null', '-'])
    niveles = []
    for m in re.finditer(r'RMS_level=(\S+)', out):
        v = m.group(1)
        niveles.append(-120.0 if 'inf' in v else max(-120.0, float(v)))
    return niveles


def umbral_automatico(niveles):
    """Entre el ruido de fondo (lo más bajo) y la voz (lo más alto), más cerca del ruido."""
    orden = sorted(niveles)
    fondo = max(orden[int(len(orden) * 0.10)], -70.0)
    voz = orden[int(len(orden) * 0.90)]
    return round(min(fondo + 0.35 * (voz - fondo), voz - 10), 1)


def detectar_silencios(path, umbral_db=None, min_silencio=MIN_SILENCIO):
    """Devuelve ([(inicio, fin), ...], umbral usado), en segundos desde el principio del vídeo.
    umbral_db=None: se calcula solo para cada vídeo (sirve también con ruido de fondo)."""
    info = info_video(path)
    if not info['audio']:
        raise RuntimeError('Este vídeo no tiene sonido: no se pueden buscar silencios.')
    niveles = medir_volumen(path)
    if not niveles:
        return [], umbral_db
    umbral = umbral_automatico(niveles) if umbral_db is None else umbral_db
    # suavizado (mediana de 3) para que un chasquido suelto no parta una pausa
    suave = [sorted(niveles[max(0, i - 1):i + 2])[len(niveles[max(0, i - 1):i + 2]) // 2]
             for i in range(len(niveles))]
    silencios, inicio = [], None
    for i, v in enumerate(suave + [0.0]):  # el 0.0 final cierra un silencio abierto
        if v < umbral and i < len(suave):
            if inicio is None:
                inicio = i
        elif inicio is not None:
            a, b = inicio * VENTANA, min(i * VENTANA, info['duracion'])
            if b - a >= min_silencio:
                silencios.append((round(a, 3), round(b, 3)))
            inicio = None
    return silencios, umbral


def proponer_cortes(silencios, duracion, margen=MARGEN, min_corte=MIN_CORTE):
    """Convierte cada silencio en un corte, dejando un margen de aire junto a la voz.
    Al principio y al final del vídeo el silencio se corta entero (sin margen hacia fuera)."""
    cortes = []
    for a, b in silencios:
        ini = 0.0 if a <= 0.05 else a + margen
        fin = duracion if b >= duracion - 0.05 else b - margen
        if fin - ini >= min_corte:
            cortes.append({'n': len(cortes) + 1, 'inicio': round(ini, 3), 'fin': round(fin, 3),
                           'duracion': round(fin - ini, 3)})
    return cortes


def tramos_a_conservar(cortes, duracion):
    """Lo que queda al quitar los cortes, en números de fotograma (a 30 fps).
    Trabajar en fotogramas enteros hace que imagen y sonido duren exactamente lo mismo."""
    total = int(duracion * FPS)  # último fotograma completo
    actual, tramos = 0, []
    for c in sorted(cortes, key=lambda c: c['inicio']):
        fa, fb = round(c['inicio'] * FPS), round(c['fin'] * FPS)
        if fa > actual:
            tramos.append((actual, min(fa, total)))
        actual = max(actual, fb)
    if actual < total:
        tramos.append((actual, total))
    return [(a, b) for a, b in tramos if b - a >= 2]


def exportar_cortado(path, cortes, modo, destino=None):
    info = info_video(path)
    tramos = tramos_a_conservar(cortes, info['duracion'])
    if not tramos:
        raise RuntimeError('Con esos cortes no quedaría nada del vídeo.')
    st = info['inicio']
    n = len(tramos)
    partes = [f'[0:v:0]setpts=PTS-{st}/TB,fps={FPS},{filtro_vertical(modo)},split={n}'
              + ''.join(f'[v{i}]' for i in range(n)),
              f'[0:a:0]asetpts=PTS-{st}/TB,aresample=48000,aformat=channel_layouts=stereo,asplit={n}'
              + ''.join(f'[a{i}]' for i in range(n))]
    for i, (fa, fb) in enumerate(tramos):
        partes.append(f'[v{i}]trim=start_frame={fa}:end_frame={fb},setpts=PTS-STARTPTS[vt{i}]')
        partes.append(f'[a{i}]atrim=start={fa / FPS:.6f}:end={fb / FPS:.6f},asetpts=PTS-STARTPTS[at{i}]')
    partes.append(''.join(f'[vt{i}][at{i}]' for i in range(n)) + f'concat=n={n}:v=1:a=1[v][a]')
    grafo = ';'.join(partes)

    out = destino or nombre_unico(f'{Path(path).stem}_cortado')
    with tempfile.TemporaryDirectory() as td:
        script = Path(td) / 'filtro.txt'
        script.write_text(grafo, encoding='utf-8')
        cmd = ['ffmpeg', '-v', 'error', '-y', '-i', str(path)]
        cmd += ['-/filter_complex', str(script)] if len(grafo) > 6000 else ['-filter_complex', grafo]
        cmd += ['-map', '[v]', '-map', '[a]', '-r', str(FPS),
                '-c:v', 'libx264', '-preset', 'medium', '-crf', '20', '-pix_fmt', 'yuv420p',
                '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart', str(out)]
        run(cmd)

    quitado = sum(c['duracion'] for c in cortes)
    informe = {
        'original': str(Path(path).resolve()),
        'resultado': str(Path(out).resolve()),
        'modo_vertical': modo,
        'duracion_original_s': round(info['duracion'], 3),
        'duracion_resultado_s': round(sum(b - a for a, b in tramos) / FPS, 3),
        'segundos_quitados_aprox': round(quitado, 3),
        'cortes_aplicados': cortes,
        'tramos_conservados_s': [[round(a / FPS, 3), round(b / FPS, 3)] for a, b in tramos],
    }
    Path(out).with_suffix('.cortes.json').write_text(
        json.dumps(informe, ensure_ascii=False, indent=2), encoding='utf-8')
    return Path(out), informe


def escuchar(path, corte):
    """Reproduce el trozo del corte con 1,5 s de contexto (si hay ffplay)."""
    if not shutil.which('ffplay'):
        print('  (No está ffplay instalado: no puedo reproducirlo.)')
        return
    ini = max(0.0, corte['inicio'] - 1.5)
    subprocess.run(['ffplay', '-v', 'error', '-autoexit', '-x', '360', '-y', '640',
                    '-window_title', f'Corte {corte["n"]}', '-ss', f'{ini:.2f}',
                    '-t', f'{corte["duracion"] + 3:.2f}', str(path)])


def revisar_cortes(path, cortes):
    """La usuaria aprueba o rechaza cada corte. Devuelve los aprobados."""
    print(f'\nCORTES PROPUESTOS ({len(cortes)}):')
    for c in cortes:
        print(f'  {c["n"]:>2}. de {reloj(c["inicio"])} a {reloj(c["fin"])}  ({c["duracion"]:.2f} s)')
    print('\n¿Cómo quieres decidir?\n  1. Uno por uno (puedes escucharlos)\n  2. Aprobar todos\n'
          '  3. Escribir los números que apruebas (ej.: 1,3,5)\n  4. Ninguno, cancelar')
    r = ask('Elige 1, 2, 3 o 4', '1')
    if r == '2':
        return list(cortes)
    if r == '4':
        return []
    if r == '3':
        nums = {int(x) for x in re.findall(r'\d+', ask('Números'))}
        return [c for c in cortes if c['n'] in nums]
    aprobados = []
    for c in cortes:
        while True:
            q = (f'  Corte {c["n"]}: {reloj(c["inicio"])} → {reloj(c["fin"])} ({c["duracion"]:.2f} s). '
                 '¿Cortar? s = sí, n = no, e = escuchar')
            r = ask(q, 's').lower()
            if r.startswith('e'):
                escuchar(path, c)
                continue
            if r.startswith('s'):
                aprobados.append(c)
            break
    return aprobados


def menu_cortar():
    if not herramientas_ok():
        return
    clips = listar_clips()
    if not clips:
        print('Coloca un vídeo MP4 o MOV en entrada/ y vuelve a intentar.')
        return
    print('\nVÍDEOS EN entrada/:')
    for i, p in enumerate(clips, 1):
        print(f'  {i}. {p.name} — {info_video(p)["duracion"]:.1f} s')
    try:
        video = clips[int(ask('¿Cuál quieres editar? (número)', '1')) - 1]
    except (ValueError, IndexError):
        print('Número no válido.')
        return

    umbral, min_sil, margen = None, MIN_SILENCIO, MARGEN
    if ask('¿Usar los ajustes recomendados (automáticos) para detectar silencios? (s/n)', 's').lower() != 's':
        r = ask('Volumen que cuenta como silencio, en dB (ej.: -35; más alto = corta más). Enter = automático', '')
        umbral = float(r.replace(',', '.')) if r else None
        min_sil = float(ask('Duración mínima del silencio, en segundos', str(MIN_SILENCIO)).replace(',', '.'))
        margen = float(ask('Aire que se deja junto a la voz, en segundos', str(MARGEN)).replace(',', '.'))

    print('Buscando silencios...')
    info = info_video(video)
    silencios, usado = detectar_silencios(video, umbral, min_sil)
    print(f'(Se ha tomado como silencio todo lo que está por debajo de {usado} dB.)')
    cortes = proponer_cortes(silencios, info['duracion'], margen)
    if not cortes:
        print('No he encontrado silencios que cortar con estos ajustes. Prueba con ajustes propios: '
              'un volumen de silencio más alto (ej.: -25) o una duración mínima más corta (ej.: 0,3).')
        return
    aprobados = revisar_cortes(video, cortes)
    if not aprobados:
        print('No se ha cortado nada. Tu vídeo sigue igual.')
        return
    modo = elegir_modo()
    print(f'Exportando con {len(aprobados)} corte(s)... (puede tardar un poco)')
    out, inf = exportar_cortado(video, aprobados, modo)
    print(f'\nVÍDEO CREADO: {out}')
    print(f'Duración: {inf["duracion_original_s"]:.2f} s → {inf["duracion_resultado_s"]:.2f} s. '
          f'Lista de cortes guardada en {out.with_suffix(".cortes.json").name}')
    print('Tu vídeo original no se ha modificado.')
    if ask('\n¿Le pongo subtítulos y efectos con tu marca ahora? (s/n)', 's').lower() == 's':
        menu_subtitulos(out)


# ---------------------------------------------------------------- subtítulos

def es_vertical_1080(video):
    try:
        w, h = [int(x) for x in run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries',
                                     'stream=width,height', '-of', 'csv=p=0', str(video)])[0].strip().split(',')[:2]]
    except Exception:
        return False
    rot = run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries',
               'stream_side_data=rotation', '-of', 'csv=p=0', str(video)])[0].strip()
    m = re.search(r'-?\d+', rot)
    if m and abs(int(m.group(0))) in (90, 270):
        w, h = h, w
    return (w, h) == (ANCHO, ALTO)


def subtitular(video, correcciones=None, destacar_extra=None, perfil=None, aviso=print, revisar=None,
               efectos_forzados=None):
    """Transcribe, agrupa, destaca, añade efectos y graba, todo según la marca activa.
    Devuelve (vídeo, srt, informe)."""
    import marca
    import subtitulos as st
    import efectos as fx
    perfil = perfil or marca.activo() or marca.base_inicial('(sin marca)')
    estilo = marca.estilo_subtitulos(perfil)
    opciones = efectos_forzados if efectos_forzados is not None else marca.efectos(perfil)

    palabras = st.transcribir(video, aviso=aviso)
    if not palabras:
        raise RuntimeError('No he oído voz en este vídeo.')
    if revisar:
        correcciones, destacar_extra = revisar(palabras)
    st.aplicar_correcciones(palabras, correcciones or {})
    elegidas = list(perfil['destacar']['palabras']) + list(destacar_extra or [])
    subs = st.marcar_destacadas(st.agrupar(palabras, max_palabras=estilo['max_palabras']),
                                elegidas, automatico=perfil['destacar']['automatico'])

    base = Path(video).stem.split('_cortado_')[0]
    out = nombre_unico(f'{base}_editado')
    ass, srt = out.with_suffix('.ass'), out.with_suffix('.srt')
    st.generar_ass(subs, estilo, ass)
    st.generar_srt(subs, srt)

    cortes_json = Path(video).with_suffix('.cortes.json')
    cortes_s = fx.cortes_desde_json(cortes_json)
    lista = fx.cargar_lista(TRABAJO / 'marca' / 'pegatinas.json')
    lista.update({fx._limpia(k): v for k, v in perfil.get('pegatinas_extra', {}).items()})
    info = {}

    def construir(td):
        entradas, cadena, overlays, peg = fx.construir(subs, cortes_s, opciones, td, lista,
                                                       ROOT / 'recursos' / 'pegatinas')
        info['pegatinas'] = [{'palabra': p['palabra'], 'segundo': round(p['inicio'], 2),
                              'pegatina': p['emoji'] or Path(p['png']).name} for p in peg]
        return entradas, cadena, overlays

    previo = '' if es_vertical_1080(video) else f'fps={FPS},{filtro_vertical(perfil["vertical"])}'
    aviso('Montando el vídeo con tu marca (subtítulos y efectos)...')
    st.grabar(video, ass, out, previo, FUENTES, efectos=construir)
    informe = {
        'marca': perfil['nombre'], 'video_origen': str(Path(video).resolve()), 'resultado': str(out),
        'estilo_subtitulos': estilo, 'efectos': opciones, 'cortes_en_el_video_s': cortes_s,
        'destacadas': [p['w'] for s in subs for p in s['palabras'] if p.get('destacada')],
        'pegatinas': info.get('pegatinas', []),
    }
    out.with_suffix('.edicion.json').write_text(json.dumps({**informe, 'subtitulos': subs},
                                                           ensure_ascii=False, indent=1), encoding='utf-8')
    return out, srt, informe


def menu_subtitulos(video=None):
    if not herramientas_ok():
        return
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        print('Falta el reconocimiento de voz (faster-whisper). Pide a Claude que lo instale o '
              'sigue INSTRUCCIONES.txt.')
        return
    import marca
    if video is None:
        opciones = listar_clips() + sorted((p for p in SALIDA.glob('*_cortado_*.mp4')),
                                           key=lambda p: p.stat().st_mtime)
        if not opciones:
            print('Coloca un vídeo en entrada/ y vuelve a intentar.')
            return
        print('\nVÍDEOS:')
        for i, p in enumerate(opciones, 1):
            print(f'  {i}. {p.parent.name}/{p.name}')
        try:
            video = opciones[int(ask('¿Cuál edito? (número)', str(len(opciones)))) - 1]
        except (ValueError, IndexError):
            print('Número no válido.')
            return
    perfil = perfil_activo()
    if perfil:
        print(f'\nSe aplica la marca de {perfil["nombre"]}:\n{marca.resumen(perfil)}')

    def revisar(palabras):
        print('\nLO QUE HE ENTENDIDO:\n')
        print('  ' + ' '.join(p['w'] for p in palabras))
        print('\n¿Alguna palabra mal escrita? Escribe «mal=bien» (ej.: Pharmacy=Farmasi). Enter para terminar.')
        corr = {}
        while True:
            r = ask('Corrección', '')
            if not r:
                break
            if '=' in r:
                a, b = r.split('=', 1)
                corr[a.strip()] = b.strip()
            else:
                print('  Usa el formato mal=bien')
        r = ask('\n¿Quieres destacar alguna palabra más SOLO en este vídeo? (separadas por comas, Enter = no)', '')
        return corr, [x.strip() for x in r.split(',') if x.strip()]

    out, srt, inf = subtitular(video, perfil=perfil, revisar=revisar)
    print(f'\nVÍDEO EDITADO: {out}')
    if inf['destacadas']:
        print('Palabras destacadas: ' + ', '.join(inf['destacadas']))
    if inf['pegatinas']:
        print('Pegatinas: ' + ', '.join(f"{p['pegatina']} en «{p['palabra']}» ({p['segundo']} s)" for p in inf['pegatinas']))
    print(f'Texto de los subtítulos (para subirlo aparte si quieres): {srt.name}')


# ---------------------------------------------------------------- referencias

def abrir(ruta):
    try:
        if sys.platform == 'win32':
            import os
            os.startfile(str(ruta))
        elif sys.platform == 'darwin':
            subprocess.Popen(['open', str(ruta)])
    except Exception:
        pass


def video_para_muestra():
    cand = sorted(SALIDA.glob('*_cortado_*.mp4'), key=lambda p: p.stat().st_mtime) or listar_clips()
    return cand[-1] if cand else None


def menu_referencias(carpeta=None, respuestas_auto=None):
    """Analiza REFERENCIAS y propone colores y estilo. respuestas_auto: dict para pruebas sin menú."""
    import marca
    import referencias as rf
    carpeta = Path(carpeta or REFERENCIAS)
    perfil = marca.activo()
    if perfil is None:
        print('Primero configura tu marca (opción 1). Después las referencias la afinan.')
        return None
    print(f'\nAnalizando las referencias de {carpeta} ...')
    a = rf.analizar(carpeta)
    if a is None:
        print('No hay capturas ni vídeos en REFERENCIAS. Ponlos en instagram/, tiktok/, pinterest/ u otras/.')
        return None
    sello = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    (carpeta / f'_analisis_{sello}.json').write_text(json.dumps(a, ensure_ascii=False, indent=1, default=list),
                                                     encoding='utf-8')
    pal_png = carpeta / f'_paleta_{sello}.png'
    rf.imagen_paleta(a['paleta'], pal_png)

    print('\nLO QUE HE VISTO:')
    for r in a['referencias']:
        linea = f"  · {r['archivo']}: "
        if 'error' in r:
            linea += 'no he podido leerlo.'
        else:
            linea += 'colores ' + ' '.join(r['colores'])
            if r['tipo'] == 'video':
                linea += (f" · {r['duracion_s']} s · {r['cambios_de_plano']} cambio(s) de plano "
                          f"(uno cada {r['segundos_por_plano']} s)")
        if r.get('nota'):
            linea += f'  — tu nota: «{r["nota"]}»'
        print(linea)
    prop = a['propuesta']
    print(f'\nPALETA (abro la imagen {pal_png.name}):')
    for i, g in enumerate(a['paleta'], 1):
        print(f'  {i}. {g["hex"]}  ({round(g["peso"] * 100)} %)')
    if respuestas_auto is None:
        abrir(pal_png)

    nuevo = marca._fusionar(perfil, {})
    resp = respuestas_auto or {}

    def elegir_color(nombre, propuesto, actual):
        if respuestas_auto is not None:
            return propuesto or actual
        txt = f'\nColor {nombre}: ahora {actual}. Propuesta: {propuesto or "ninguna"}. ' \
              'Enter = propuesta · número de la paleta · n = dejar el actual'
        r = ask(txt, '')
        if r.lower() == 'n':
            return actual
        if r.isdigit() and 1 <= int(r) <= len(a['paleta']):
            return a['paleta'][int(r) - 1]['hex']
        return propuesto or actual

    nuevo['colores']['principal'] = elegir_color('principal (palabras destacadas)', prop['principal'],
                                                 perfil['colores']['principal'])
    nuevo['colores']['secundario'] = elegir_color('secundario (marcador y detalles)', prop['secundario'],
                                                  perfil['colores']['secundario'])
    if prop['estilo']:
        print(f"\nRitmo de tus referencias: un cambio de plano cada {prop['segundos_por_plano']} s "
              f"→ estilo «{marca.ESTILOS[prop['estilo']][0]}». (Ahora tienes «{marca.ESTILOS[perfil['estilo']][0]}».)")
        if respuestas_auto is not None or ask('¿Uso ese estilo? (s/n)', 's').lower() == 's':
            nuevo['estilo'] = prop['estilo']
    if prop['duracion_tipica_s']:
        print(f"Duración típica de tus referencias: {prop['duracion_tipica_s']} s.")
        nuevo['duracion_tipica_s'] = prop['duracion_tipica_s']
    nuevo['referencias_analizadas'] = [r['archivo'] for r in a['referencias'] if 'error' not in r]

    v = video_para_muestra()
    if v:
        muestra = carpeta / f'_muestra_{sello}.png'
        previo = '' if es_vertical_1080(v) else f'fps={FPS},{filtro_vertical(nuevo["vertical"])}'
        rf.muestra_estilo(v, marca.estilo_subtitulos(nuevo), muestra, previo, segundo=1.0)
        print(f'\nAsí quedarían tus subtítulos (abro {muestra.name}).')
        if respuestas_auto is None:
            abrir(muestra)
    print('\nTU MARCA CON LOS CAMBIOS:\n' + marca.resumen(nuevo))
    if respuestas_auto is not None:
        guardar = resp.get('guardar', True)
    else:
        guardar = ask('\n¿La guardo así? (s/n)', 's').lower() == 's'
    if guardar:
        marca.guardar(nuevo)
        print('Marca actualizada. Se aplicará sola a tus próximos vídeos.')
    else:
        print('No he cambiado tu marca.')
    return a


# ---------------------------------------------------------------- sin menú

def cli(argv):
    ap = argparse.ArgumentParser(prog='content_studio.py cortar',
                                 description='Corta los silencios de un vídeo y lo exporta en vertical 1080x1920.')
    ap.add_argument('video')
    ap.add_argument('--aprobar', default='todos',
                    help='"todos", "ninguno" o números separados por comas (ej.: 1,3). Por defecto: todos')
    ap.add_argument('--modo', choices=list(MODOS), default='recortar')
    ap.add_argument('--umbral', type=float, default=None,
                    help='dB que cuentan como silencio (por defecto: automático para cada vídeo)')
    ap.add_argument('--min-silencio', type=float, default=MIN_SILENCIO)
    ap.add_argument('--margen', type=float, default=MARGEN)
    ap.add_argument('--solo-proponer', action='store_true', help='solo lista los cortes, no exporta')
    a = ap.parse_args(argv)
    if not herramientas_ok():
        return 1
    info = info_video(a.video)
    silencios, usado = detectar_silencios(a.video, a.umbral, a.min_silencio)
    print(f'umbral de silencio: {usado} dB')
    cortes = proponer_cortes(silencios, info['duracion'], a.margen)
    for c in cortes:
        print(f'{c["n"]:>2}. {c["inicio"]:.3f} -> {c["fin"]:.3f}  ({c["duracion"]:.3f} s)')
    if a.solo_proponer:
        return 0
    if a.aprobar == 'todos':
        aprobados = cortes
    elif a.aprobar == 'ninguno':
        aprobados = []
    else:
        nums = {int(x) for x in re.findall(r'\d+', a.aprobar)}
        aprobados = [c for c in cortes if c['n'] in nums]
    if not aprobados:
        print('Ningún corte aprobado: no se exporta nada.')
        return 0
    out, inf = exportar_cortado(a.video, aprobados, a.modo)
    print(json.dumps(inf, ensure_ascii=False, indent=2))
    return 0


def cli_subtitular(argv):
    ap = argparse.ArgumentParser(prog='content_studio.py subtitular',
                                 description='Subtítulos y efectos con la marca activa.')
    ap.add_argument('video')
    ap.add_argument('--corregir', default='', help='correcciones "mal=bien;mal2=bien2"')
    ap.add_argument('--destacar', default='', help='palabras extra solo para este vídeo, separadas por comas')
    ap.add_argument('--marca', default='', help='nombre del archivo de marca/perfiles (por defecto: la activa)')
    a = ap.parse_args(argv)
    import marca
    perfil = marca.cargar(marca.CARPETA / a.marca) if a.marca else None
    corr = dict(x.split('=', 1) for x in a.corregir.split(';') if '=' in x)
    dest = [x.strip() for x in a.destacar.split(',') if x.strip()]
    out, srt, inf = subtitular(a.video, corr, dest, perfil=perfil)
    print(json.dumps(inf, ensure_ascii=False, indent=1))
    return 0


# ---------------------------------------------------------------- órdenes para el chat de Claude
# Todo sin preguntas: Claude pregunta en el chat (con botones) y luego llama a estas órdenes.
# Cada orden termina con una línea «RESULTADO: {json}» que Claude lee.

def _resultado(datos, codigo=0):
    print('RESULTADO: ' + json.dumps(datos, ensure_ascii=False))
    return codigo


def _normalizar_marca(p):
    """Corrige valores que llegan del chat (colores por nombre, letras, opciones válidas)."""
    import marca
    avisos = []
    base = marca.PLANTILLA
    for k in ('principal', 'secundario', 'texto'):
        p['colores'][k] = marca.color(str(p['colores'].get(k) or ''), base['colores'][k])
    for k in ('subtitulos', 'destacado'):
        nombre = (p['tipografias'].get(k) or '').strip()
        if not nombre:
            if k == 'subtitulos':
                p['tipografias'][k] = base['tipografias'][k]
            continue
        exacta, parecidas = marca.comprobar_fuente(nombre)
        if exacta:
            p['tipografias'][k] = exacta
        else:
            avisos.append(f'La letra «{nombre}» no está en este ordenador; se usa Poppins'
                          + (f' (parecidas: {", ".join(parecidas)})' if parecidas else '') + '.')
            p['tipografias'][k] = 'Poppins' if k == 'subtitulos' else ''
    s, sb = p['subtitulos'], base['subtitulos']
    validos = {'posicion': ('pecho', 'centro', 'abajo'), 'mayusculas': ('minusculas', 'mayusculas', 'normal'),
               'borde': ('sombra', 'contorno', 'ninguno'), 'destacado': ('color', 'marcador')}
    for k, opciones in validos.items():
        if s.get(k) not in opciones:
            s[k] = sb[k]
    try:
        s['tamano'] = min(140, max(48, int(s['tamano'])))
    except (TypeError, ValueError):
        s['tamano'] = sb['tamano']
    try:
        s['palabras'] = min(3, max(1, int(s['palabras'])))
    except (TypeError, ValueError):
        s['palabras'] = sb['palabras']
    if p.get('estilo') not in marca.ESTILOS:
        p['estilo'] = base['estilo']
    if p.get('vertical') not in MODOS:
        p['vertical'] = base['vertical']
    if isinstance(p['destacar'].get('palabras'), str):
        p['destacar']['palabras'] = [x.strip() for x in p['destacar']['palabras'].split(',') if x.strip()]
    return avisos


def muestra_marca(perfil, video=None):
    """PNG 1080x1920 con un subtítulo de ejemplo en el estilo de la marca (sobre el vídeo o un fondo)."""
    import marca
    import subtitulos as st
    destino = nombre_unico('muestra_marca', '.png')
    estilo = marca.estilo_subtitulos(perfil)
    subs = [{'inicio': 0.0, 'fin': 99.0, 'palabras': [
        {'w': 'así', 'start': 0, 'end': 1}, {'w': 'se', 'start': 0, 'end': 1},
        {'w': 'verán', 'start': 0, 'end': 1, 'destacada': True}]}]
    with tempfile.TemporaryDirectory() as td:
        st.generar_ass(subs, estilo, Path(td) / 'subs.ass')
        (Path(td) / 'fuentes').mkdir()
        for f in FUENTES.iterdir():
            if f.suffix.lower() in ('.ttf', '.otf'):
                (Path(td) / 'fuentes' / f.name).write_bytes(f.read_bytes())
        if video:
            entrada = ['-ss', '1', '-i', str(Path(video).resolve())]
            previo = f'{filtro_vertical(perfil["vertical"])},'
        else:
            entrada = ['-f', 'lavfi', '-i', f'color=c=0x5A5A66:s={ANCHO}x{ALTO}']
            previo = ''
        p = subprocess.run(['ffmpeg', '-v', 'error', '-y', *entrada, '-frames:v', '1',
                            '-vf', f'{previo}subtitles=subs.ass:fontsdir=fuentes', str(destino)],
                           cwd=td, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                           encoding='utf-8', errors='replace')
        if p.returncode:
            raise RuntimeError(p.stderr[-1000:])
    return destino


def cli_marca(argv):
    import marca
    ap = argparse.ArgumentParser(prog='content_studio.py marca')
    ap.add_argument('accion', choices=['ver', 'guardar', 'cambiar', 'activar', 'muestra'])
    ap.add_argument('--datos', default='', help='JSON con los campos de la ficha (guardar/cambiar)')
    ap.add_argument('--archivo', default='', help='archivo JSON con los datos, en vez de --datos')
    ap.add_argument('--nombre', default='', help='usuaria a activar')
    ap.add_argument('--video', default='', help='muestra: vídeo de fondo')
    a = ap.parse_args(argv)

    if a.accion == 'ver':
        p = marca.activo()
        return _resultado({'activa': p, 'usuarias': [marca.cargar(r)['nombre'] for r in marca.listar()],
                           'estilo_de_partida': marca.base_inicial(),
                           'estilos': {k: v[0] for k, v in marca.ESTILOS.items()},
                           'letras_incluidas': ['Poppins', 'Montserrat', 'Anton', 'Playfair Display',
                                                'Dancing Script']})
    if a.accion == 'activar':
        for r in marca.listar():
            if marca.cargar(r)['nombre'].lower() == a.nombre.lower() or r.stem == marca._slug(a.nombre):
                marca.activar(r)
                return _resultado({'activa': marca.cargar(r)})
        return _resultado({'error': f'No hay ninguna usuaria llamada «{a.nombre}».'}, 1)
    if a.accion == 'muestra':
        p = marca.activo() or marca.base_inicial('(sin marca)')
        return _resultado({'muestra': str(muestra_marca(p, a.video or None))})

    texto = Path(a.archivo).read_text(encoding='utf-8') if a.archivo else a.datos
    try:
        datos = json.loads(texto or '{}')
    except json.JSONDecodeError as e:
        return _resultado({'error': f'Datos de marca no válidos: {e}'}, 1)
    base = marca.activo() if a.accion == 'cambiar' else None
    if a.accion == 'cambiar' and base is None:
        return _resultado({'error': 'Todavía no hay marca: usa «guardar».'}, 1)
    p = marca._fusionar(base or marca.base_inicial(), datos)
    if not str(p.get('nombre', '')).strip():
        return _resultado({'error': 'Falta el nombre de la usuaria.'}, 1)
    avisos = _normalizar_marca(p)
    ruta = marca.guardar(p)
    return _resultado({'guardada': str(ruta), 'marca': p, 'avisos': avisos,
                       'muestra': str(muestra_marca(p))})


def unir_clips(clips, modo):
    """Une los vídeos en el orden dado en un vertical 1080x1920. Devuelve la ruta."""
    with tempfile.TemporaryDirectory() as td:
        normalizados = []
        for i, p in enumerate(clips):
            tiene_audio = info_video(p)['audio']
            out = Path(td) / f'clip_{i:03d}.mp4'
            cmd = ['ffmpeg', '-v', 'error', '-y', '-i', str(p)]
            if not tiene_audio:
                cmd += ['-f', 'lavfi', '-i', 'anullsrc=channel_layout=stereo:sample_rate=48000']
            cmd += ['-filter_complex', f'[0:v:0]fps={FPS},{filtro_vertical(modo)}[v]',
                    '-map', '[v]', '-map', '0:a:0' if tiene_audio else '1:a:0',
                    '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20', '-pix_fmt', 'yuv420p',
                    '-c:a', 'aac', '-b:a', '192k', '-ar', '48000', '-ac', '2']
            if not tiene_audio:
                cmd += ['-shortest']
            run(cmd + [str(out)])
            normalizados.append(out)
        lst = Path(td) / 'lista.txt'
        lst.write_text(''.join("file '" + str(p).replace("'", "'\\''") + "'\n" for p in normalizados),
                       encoding='utf-8')
        out = nombre_unico('reel_unido')
        run(['ffmpeg', '-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', str(lst),
             '-c', 'copy', '-movflags', '+faststart', str(out)])
    return out


def cli_editar(argv):
    """Edición completa de una vez: (unir) -> cortar silencios -> subtítulos y efectos de la marca."""
    import marca
    ap = argparse.ArgumentParser(prog='content_studio.py editar')
    ap.add_argument('videos', nargs='+', help='uno o varios vídeos (varios = se unen en ese orden)')
    ap.add_argument('--sin-cortes', action='store_true', help='no quitar silencios')
    ap.add_argument('--sin-subtitulos', action='store_true', help='solo cortes y vertical')
    ap.add_argument('--estilo', choices=list(marca.ESTILOS), default=None, help='solo para este vídeo')
    ap.add_argument('--destacar', default='', help='palabras extra solo para este vídeo, separadas por comas')
    ap.add_argument('--efectos', default=None,
                    help='solo para este vídeo: "zoom,pegatinas,destellos" (los que quieras) o "ninguno"')
    a = ap.parse_args(argv)
    if not herramientas_ok():
        return _resultado({'error': 'Falta FFmpeg.'}, 1)
    # un nombre suelto se busca en entrada/ («todos» = todos los de entrada/, en orden)
    if [v.lower() for v in a.videos] == ['todos']:
        a.videos = [str(p) for p in listar_clips()]
    videos = []
    for v in a.videos:
        p = Path(v).expanduser()
        videos.append(p if p.is_file() or not (ENTRADA / v).is_file() else ENTRADA / v)
    faltan = [str(v) for v in videos if not v.is_file()]
    if faltan or not videos:
        return _resultado({'error': 'No encuentro estos vídeos: ' + (', '.join(faltan) or 'entrada/ está vacía')}, 1)
    perfil = marca.activo() or marca.base_inicial('(sin marca)')
    if a.estilo:
        perfil['estilo'] = a.estilo
    efectos_video = marca.efectos(perfil)
    if a.efectos is not None:
        pedidos = {x.strip().lower() for x in a.efectos.split(',')}
        efectos_video = {k: k in pedidos for k in efectos_video}
    modo = perfil['vertical']
    res = {'marca': perfil['nombre'], 'originales': [str(v) for v in videos]}

    video = videos[0]
    if len(videos) > 1:
        print(f'Uniendo {len(videos)} vídeos...', flush=True)
        video = unir_clips(videos, modo)
        res['unido'] = str(video)
    info = info_video(video)
    res['duracion_original_s'] = round(info['duracion'], 2)

    if not a.sin_cortes:
        print('Buscando silencios...', flush=True)
        silencios, _ = detectar_silencios(video, None, MIN_SILENCIO)
        cortes = proponer_cortes(silencios, info['duracion'], MARGEN)
        res['silencios_quitados'] = len(cortes)
        if cortes:
            print(f'Quitando {len(cortes)} silencio(s)...', flush=True)
            video, _ = exportar_cortado(video, cortes, modo)
            res['cortado'] = str(video)

    if a.sin_subtitulos:
        if 'cortado' not in res:   # sin cortes ni subtítulos: al menos se pasa a vertical
            video, _ = exportar_cortado(video, [], modo)
        res['resultado'] = str(video)
    else:
        print('Escuchando el vídeo para los subtítulos (la primera vez tarda más)...', flush=True)
        dest = [x.strip() for x in a.destacar.split(',') if x.strip()]
        out, srt, inf = subtitular(video, destacar_extra=dest, perfil=perfil,
                                   efectos_forzados=efectos_video,
                                   aviso=lambda m: print(m, flush=True))
        ed = json.loads(out.with_suffix('.edicion.json').read_text(encoding='utf-8'))
        res.update({'resultado': str(out), 'subtitulos_srt': str(srt),
                    'texto': ' '.join(p['w'] for s in ed['subtitulos'] for p in s['palabras']),
                    'destacadas': inf['destacadas'], 'pegatinas': inf['pegatinas'], 'efectos': efectos_video,
                    'para_corregir': str(video)})
    res['duracion_final_s'] = round(info_video(res['resultado'])['duracion'], 2)
    return _resultado(res)


def cli_estado(argv):
    """Lo que Claude necesita saber al empezar: carpeta, marca, vídeos por editar, referencias y editados."""
    import marca
    p = marca.activo()
    refs = [x for x in REFERENCIAS.rglob('*') if x.is_file()
            and x.suffix.lower() in VIDEO_EXT + ('.jpg', '.jpeg', '.png', '.webp')]
    editados = sorted(SALIDA.glob('*_editado_*.mp4'), key=lambda x: x.stat().st_mtime, reverse=True)
    return _resultado({
        'version': VERSION, 'motor': str(ROOT), 'carpeta': str(TRABAJO),
        'instalado': VENV_PY.exists() and bool(shutil.which('ffmpeg')),
        'marca': p['nombre'] if p else None,
        'usuarias': [marca.cargar(r)['nombre'] for r in marca.listar()],
        'videos_para_editar': [{'archivo': x.name, 'segundos': round(info_video(x)['duracion'], 1)}
                               for x in listar_clips()],
        'referencias': [str(x.relative_to(REFERENCIAS)) for x in refs][:30],
        'ultimos_editados': [x.name for x in editados[:5]],
    })


SKILL_DESTINO = Path.home() / '.claude' / 'skills' / 'content-studio'
MARCA_CLAUDE = '<!-- carpeta de Content Studio IA -->'


def cli_preparar(argv):
    """Crea (o actualiza) la carpeta de trabajo de una chica e instala la skill de Claude Code.
    Uso: content_studio.py --carpeta "<su carpeta>" preparar"""
    if TRABAJO == ROOT:
        return _resultado({'error': 'Indica su carpeta con --carpeta "<ruta>".'}, 1)
    py = VENV_PY if VENV_PY.exists() else Path(sys.executable)
    plantilla = (ROOT / 'skill' / 'SKILL.md').read_text(encoding='utf-8')
    texto = (plantilla.replace('{{PYTHON}}', py.as_posix())
             .replace('{{MOTOR}}', ROOT.as_posix())
             .replace('{{CARPETA}}', TRABAJO.as_posix())
             .replace('{{VERSION}}', VERSION))
    SKILL_DESTINO.mkdir(parents=True, exist_ok=True)
    (SKILL_DESTINO / 'SKILL.md').write_text(texto, encoding='utf-8')

    claude_md = TRABAJO / 'CLAUDE.md'
    nota = None
    if claude_md.exists() and MARCA_CLAUDE not in claude_md.read_text(encoding='utf-8', errors='replace'):
        nota = 'Ya había un CLAUDE.md propio en la carpeta: no lo he tocado.'
    else:
        claude_md.write_text(
            f'{MARCA_CLAUDE}\n# Mi carpeta de Content Studio IA\n\n'
            'Aquí se editan mis vídeos con Content Studio IA, hablando con Claude. Para todo lo que tenga que ver\n'
            'con vídeos, mi marca o mis referencias, usa siempre la skill **content-studio** (sin menús ni terminal).\n\n'
            '- `entrada/`: los vídeos que quiero editar.\n'
            '- `salida/`: los vídeos terminados.\n'
            '- `marca/`: mi marca (colores, letras, estilo).\n'
            '- `REFERENCIAS/`: capturas o vídeos que me gustan.\n\n'
            'Si la skill content-studio no aparece, Content Studio IA no está instalado o hay que reiniciar Claude:\n'
            'díselo en una frase y sigue el INSTALAR.md de https://github.com/contentstudioiaAMRB/content-studio-ia\n',
            encoding='utf-8')
    (TRABAJO / 'EMPIEZA AQUÍ.txt').write_text(
        'CONTENT STUDIO IA — CÓMO EDITAR TU VÍDEO\n\n'
        '1. Pon tu vídeo en la carpeta «entrada» (arrástralo ahí).\n'
        '2. Abre Claude, pestaña Code, y empieza una conversación nueva eligiendo esta carpeta:\n'
        '   Escritorio → Content Studio ediciones. (Si pregunta si confías en la carpeta, di que sí.)\n'
        '3. Escribe:  Hola, edita mi vídeo\n'
        '4. Tu vídeo editado aparece en la carpeta «salida». Tu original no se toca.\n\n'
        'Para cambiar algo, díselo en la misma conversación: «hazlo más corto», «ponle stickers»,\n'
        '«cambia el color de los subtítulos»… La primera vez, Claude te enseña el estilo de partida\n'
        'y te pregunta si lo usas o lo cambias.\n\n'
        'Si Claude te pide permiso para ejecutar algo del programa, pulsa «Permitir siempre».\n',
        encoding='utf-8')
    return _resultado({'carpeta': str(TRABAJO), 'skill': str(SKILL_DESTINO / 'SKILL.md'), 'nota': nota})


def main():
    print(f'\nCONTENT STUDIO IA — versión {VERSION}')
    perfil = perfil_activo(avisar=False)
    print(f'Marca activa: {perfil["nombre"]}' if perfil else 'Todavía no has configurado tu marca (opción 1).')
    print('1. Configurar mi marca\n2. Ver mi marca\n3. Unir mis videos en formato vertical\n'
          '4. Cortar silencios de un video\n5. Subtítulos y efectos con mi marca\n'
          '6. Cambiar de usuaria\n7. Analizar mis referencias (colores y ritmo)\n8. Salir\n'
          f'(Tus referencias van en la carpeta REFERENCIAS: {REFERENCIAS})')
    while True:
        try:
            n = ask('\nElige un número del 1 al 8')
        except EOFError:
            break
        try:
            if n == '1':
                brand()
            elif n == '2':
                ver_marca()
            elif n == '3':
                unir()
            elif n == '4':
                menu_cortar()
            elif n == '5':
                menu_subtitulos()
            elif n == '6':
                cambiar_usuaria()
            elif n == '7':
                menu_referencias()
            elif n == '8':
                break
            else:
                print('Opción no reconocida.')
        except EOFError:
            break
        except Exception as e:
            print('Error:', e)


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'cortar':
        sys.exit(cli(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == 'subtitular':
        sys.exit(cli_subtitular(sys.argv[2:]))
    ordenes = {'marca': cli_marca, 'editar': cli_editar, 'estado': cli_estado, 'preparar': cli_preparar}
    if len(sys.argv) > 1 and sys.argv[1] in ordenes:
        try:
            sys.exit(ordenes[sys.argv[1]](sys.argv[2:]))
        except SystemExit:
            raise
        except Exception as e:   # el chat necesita una línea clara, no un volcado
            sys.exit(_resultado({'error': str(e)[-1500:]}, 1))
    if len(sys.argv) > 1 and sys.argv[1] == 'referencias':
        ap = argparse.ArgumentParser(prog='content_studio.py referencias')
        ap.add_argument('--carpeta', default=None)
        ap.add_argument('--no-guardar', action='store_true', help='solo analiza y enseña la propuesta')
        a = ap.parse_args(sys.argv[2:])
        menu_referencias(a.carpeta, respuestas_auto={'guardar': not a.no_guardar})
        sys.exit(0)
    main()

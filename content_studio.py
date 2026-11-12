"""Content Studio IA - versión 0.6.

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

VERSION = '0.6'
ROOT = Path(__file__).resolve().parent
ENTRADA = ROOT / 'entrada'
SALIDA = ROOT / 'salida'
PROFILE = ROOT / 'marca' / 'perfil.json'
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

REFERENCIAS = ROOT / 'REFERENCIAS'


def preparar_carpetas():
    for d in ('entrada', 'salida', 'marca', 'recursos', 'recursos/fuentes', 'recursos/pegatinas'):
        (ROOT / d).mkdir(parents=True, exist_ok=True)
    # la antigua carpeta «referencias» pasa a llamarse REFERENCIAS (con su contenido)
    for p in ROOT.iterdir():
        if p.is_dir() and p.name.lower() == 'referencias' and p.name != 'REFERENCIAS':
            p.rename(ROOT / '__ref_tmp')
            (ROOT / '__ref_tmp').rename(REFERENCIAS)
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
            cmd += [str(out)]
            print('Procesando', p.name, '...')
            run(cmd)
            normalizados.append(out)
        lst = Path(td) / 'lista.txt'
        lst.write_text(''.join("file '" + str(p).replace("'", "'\\''") + "'\n" for p in normalizados),
                       encoding='utf-8')
        out = nombre_unico('reel_unido')
        run(['ffmpeg', '-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', str(lst),
             '-c', 'copy', '-movflags', '+faststart', str(out)])
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
    perfil = perfil or marca.activo() or marca._fusionar(marca.PLANTILLA, {'nombre': '(sin marca)'})
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
    lista = fx.cargar_lista(ROOT / 'marca' / 'pegatinas.json')
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
    if len(sys.argv) > 1 and sys.argv[1] == 'referencias':
        ap = argparse.ArgumentParser(prog='content_studio.py referencias')
        ap.add_argument('--carpeta', default=None)
        ap.add_argument('--no-guardar', action='store_true', help='solo analiza y enseña la propuesta')
        a = ap.parse_args(sys.argv[2:])
        menu_referencias(a.carpeta, respuestas_auto={'guardar': not a.no_guardar})
        sys.exit(0)
    main()

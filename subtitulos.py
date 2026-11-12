"""Content Studio IA - subtítulos automáticos (etapa 2).

Transcribe la voz en este ordenador con faster-whisper (modelo abierto de Whisper),
agrupa las palabras en subtítulos de 1 a 3 palabras, marca palabras destacadas y
los graba sobre el vídeo con FFmpeg (libass). Nada sale del ordenador.
"""
import json
import re
import subprocess
import tempfile
import unicodedata
from pathlib import Path

MODELO = 'large-v3-turbo'   # más preciso; 'small' es unas 3 veces más rápido pero falla más

ESTILO_POR_DEFECTO = {
    'fuente': 'Poppins',          # nombre de una letra instalada en el ordenador o en recursos/fuentes
    'negrita': True,
    'fuente_destacado': '',       # vacío = la misma letra
    'tamano': 80,                 # píxeles sobre un vídeo de 1080x1920
    'color': '#FFFFFF',
    'color_destacado': '#E8C77A',
    'mayusculas': 'minusculas',   # minusculas | mayusculas | normal
    'contorno': 'sombra',         # sombra | contorno | ninguno
    'posicion': 'pecho',          # pecho | centro | abajo
    'max_palabras': 3,
}

# distancia desde el borde de abajo (fuera del 18 % inferior, donde Instagram/TikTok ponen su texto)
POSICIONES = {'pecho': 570, 'abajo': 420, 'centro': 0}

PALABRAS_VACIAS = set('''a al algo ante antes aqui así asi aunque bien cada como con contra cual
cuando de del desde donde dos el ella ellas ellos en entre era es esa ese eso esta este esto estos
estas fue ha hay la las le les lo los mas más me mi mis muy nada ni no nos o otra otro para pero
poco por porque que qué se sea ser si sí sin sobre solo son su sus también tan te tengo tiene
tienen todo todos tu tú un una uno unos unas usted ustedes va vamos y ya yo'''.split())


def _run(cmd, cwd=None):
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                       encoding='utf-8', errors='replace', cwd=cwd)
    if p.returncode:
        raise RuntimeError(p.stderr[-2500:])
    return p.stdout


def _limpia(w):
    w = unicodedata.normalize('NFKD', w.lower())
    return re.sub(r'[^a-z0-9ñ]', '', ''.join(c for c in w if not unicodedata.combining(c)))


# ---------------------------------------------------------------- transcripción

def transcribir(video, modelo=MODELO, idioma='es', aviso=print):
    """Devuelve [{'w': palabra, 'start': s, 'end': s}, ...] en segundos del vídeo."""
    import numpy as np
    from faster_whisper import WhisperModel
    # el audio se decodifica con FFmpeg (mono, 16 kHz) y se le pasa a Whisper ya preparado
    p = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(video), '-map', '0:a:0', '-vn',
                        '-ac', '1', '-ar', '16000', '-f', 'f32le', '-'],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode:
        raise RuntimeError(p.stderr.decode('utf-8', 'replace')[-2000:])
    audio = np.frombuffer(p.stdout, dtype=np.float32)
    aviso(f'Cargando el modelo de voz ({modelo}). La primera vez puede tardar en descargarse...')
    m = WhisperModel(modelo, device='cpu', compute_type='int8')
    aviso('Transcribiendo...')
    segmentos, _ = m.transcribe(audio, language=idioma, word_timestamps=True,
                                vad_filter=True, beam_size=5,
                                condition_on_previous_text=False)
    palabras = []
    for s in segmentos:
        for w in s.words or []:
            t = w.word.strip()
            if t:
                palabras.append({'w': t, 'start': round(w.start, 3), 'end': round(w.end, 3)})
    return palabras


def aplicar_correcciones(palabras, correcciones):
    """correcciones: {'Pharmacy': 'Farmasi'} — compara sin mayúsculas, tildes ni signos."""
    mapa = {_limpia(k): v for k, v in correcciones.items() if _limpia(k)}
    for p in palabras:
        clave = _limpia(p['w'])
        if clave in mapa:
            pre = re.match(r'^[¡¿"“(]*', p['w']).group(0)
            post = re.search(r'[.,;:!?…"”)]*$', p['w']).group(0)
            p['w'] = pre + mapa[clave] + post
    return palabras


# ---------------------------------------------------------------- agrupar y destacar

def agrupar(palabras, max_palabras=3, max_letras=18, pausa=0.35):
    grupos, actual = [], []
    for i, p in enumerate(palabras):
        if actual:
            letras = sum(len(x['w']) + 1 for x in actual) + len(p['w'])
            hueco = p['start'] - actual[-1]['end']
            if len(actual) >= max_palabras or letras > max_letras or hueco > pausa \
                    or re.search(r'[.!?…,;:]$', actual[-1]['w']):
                grupos.append(actual)
                actual = []
        actual.append(p)
    if actual:
        grupos.append(actual)
    # un subtítulo no termina en «y», «para», «que»...: esa palabra pasa al siguiente
    for i in reversed(range(len(grupos) - 1)):
        g, sig = grupos[i], grupos[i + 1]
        while (len(g) >= 2 and _limpia(g[-1]['w']) in PALABRAS_VACIAS
               and not re.search(r'[.!?…,;:]$', g[-1]['w'])
               and sig[0]['start'] - g[-1]['end'] < pausa and len(sig) < max_palabras):
            sig.insert(0, g.pop())
    subs = []
    for i, g in enumerate(grupos):
        ini, fin = g[0]['start'], g[-1]['end'] + 0.15
        if i + 1 < len(grupos):
            sig = grupos[i + 1][0]['start']
            fin = sig if sig - g[-1]['end'] < 0.3 else min(fin, sig)
        fin = max(fin, ini + 0.4)
        subs.append({'inicio': round(ini, 3), 'fin': round(fin, 3), 'palabras': [dict(x) for x in g]})
    # que ninguno se monte sobre el siguiente
    for a, b in zip(subs, subs[1:]):
        a['fin'] = min(a['fin'], b['inicio'])
    return subs


def marcar_destacadas(subs, elegidas=None, automatico=None, cada=2.5):
    """elegidas: palabras de la usuaria (siempre se destacan).
    automatico: además, como mucho una cada ~2,5 s, la palabra más larga (6 letras o más)
    que no sea una palabra vacía. Por defecto, automático solo si no hay lista."""
    if automatico is None:
        automatico = not elegidas
    claves = {_limpia(e) for e in (elegidas or []) if _limpia(e)}
    ultima = -99.0
    for s in subs:
        for p in s['palabras']:
            p['destacada'] = _limpia(p['w']) in claves
        if any(p['destacada'] for p in s['palabras']):
            ultima = s['inicio']
            continue
        if not automatico:
            continue
        cand = [p for p in s['palabras'] if len(_limpia(p['w'])) >= 6 and _limpia(p['w']) not in PALABRAS_VACIAS]
        if cand and s['inicio'] - ultima >= cada:
            max(cand, key=lambda p: len(_limpia(p['w'])))['destacada'] = True
            ultima = s['inicio']
    return subs


# ---------------------------------------------------------------- ASS / SRT

def _color_ass(hexrgb, alfa=0):
    h = hexrgb.lstrip('#')
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f'&H{alfa:02X}{b}{g}{r}'.upper()


def _t_ass(t):
    cs = int(round(t * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f'{h}:{m:02d}:{s:02d}.{cs:02d}'


def _texto(w, estilo):
    w = w.replace('{', '').replace('}', '').replace('\\', '')
    if estilo['mayusculas'] == 'mayusculas':
        return w.upper()
    if estilo['mayusculas'] == 'minusculas':
        return w.lower()
    return w


def generar_ass(subs, estilo, destino):
    e = {**ESTILO_POR_DEFECTO, **estilo}
    if e['contorno'] == 'contorno':
        borde, outline, shadow, back = 1, 6, 0, _color_ass('#000000', 0)
    elif e['contorno'] == 'sombra':
        borde, outline, shadow, back = 1, 2, 4, _color_ass('#000000', 0x60)
    else:
        borde, outline, shadow, back = 1, 0, 0, _color_ass('#000000', 0xFF)
    margen_v = POSICIONES.get(e['posicion'], POSICIONES['pecho'])
    alin = 5 if e['posicion'] == 'centro' else 2
    cab = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Sub,{e['fuente']},{e['tamano']},{_color_ass(e['color'])},{_color_ass(e['color'])},{_color_ass('#000000')},{back},{-1 if e['negrita'] else 0},0,0,0,100,100,0,0,{borde},{outline},{shadow},{alin},90,90,{0 if alin == 5 else margen_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lineas = []
    col_d = _color_ass(e['color_destacado'])
    for s in subs:
        trozos = []
        for p in s['palabras']:
            t = _texto(p['w'], e)
            if p.get('destacada'):
                fd = f"\\fn{e['fuente_destacado']}" if e['fuente_destacado'] else ''
                if e.get('cursiva_destacado'):
                    fd += '\\i1'
                if e.get('destacado') == 'marcador':
                    col_m = _color_ass(e.get('color_marcador') or e['color_destacado'])
                    trozos.append(f"{{\\3c{col_m}\\bord12\\shad0{fd}\\fscx108\\fscy108}}{t}{{\\r}}")
                else:
                    trozos.append(f"{{\\c{col_d}{fd}\\fscx108\\fscy108}}{t}{{\\r}}")
            else:
                trozos.append(t)
        # pequeña entrada: aparece creciendo del 92 % al 100 % en 80 ms
        texto = '{\\fscx92\\fscy92\\t(0,80,\\fscx100\\fscy100)}' + ' '.join(trozos)
        lineas.append(f"Dialogue: 0,{_t_ass(s['inicio'])},{_t_ass(s['fin'])},Sub,,0,0,0,,{texto}")
    Path(destino).write_text(cab + '\n'.join(lineas) + '\n', encoding='utf-8-sig')


def generar_srt(subs, destino):
    def t(x):
        ms = int(round(x * 1000))
        h, ms = divmod(ms, 3600000)
        m, ms = divmod(ms, 60000)
        s, ms = divmod(ms, 1000)
        return f'{h:02d}:{m:02d}:{s:02d},{ms:03d}'
    bloques = [f"{i}\n{t(s['inicio'])} --> {t(s['fin'])}\n{' '.join(p['w'] for p in s['palabras'])}\n"
               for i, s in enumerate(subs, 1)]
    Path(destino).write_text('\n'.join(bloques), encoding='utf-8')


def grabar(video, ass, destino, filtro_previo='', carpeta_fuentes=None, efectos=None):
    """Graba los subtítulos sobre el vídeo. filtro_previo: p. ej. el paso a vertical.
    efectos: función(carpeta_temporal) -> (entradas_extra, cadena, overlays) de efectos.py."""
    with tempfile.TemporaryDirectory() as td:
        # se trabaja con nombres relativos para evitar los problemas de las rutas de Windows en los filtros
        Path(td, 'subs.ass').write_bytes(Path(ass).read_bytes())
        fuentes = ''
        if carpeta_fuentes and Path(carpeta_fuentes).is_dir() and any(Path(carpeta_fuentes).iterdir()):
            dst = Path(td, 'fuentes')
            dst.mkdir()
            for f in Path(carpeta_fuentes).iterdir():
                if f.suffix.lower() in ('.ttf', '.otf'):
                    (dst / f.name).write_bytes(f.read_bytes())
            fuentes = ':fontsdir=fuentes'
        entradas, cadena, overlays = efectos(td) if efectos else ([], '', [])
        vf = ','.join(x for x in (filtro_previo, cadena, f'subtitles=subs.ass{fuentes}') if x)
        grafo = [f'[0:v:0]{vf}[b]']
        final = '[b]'
        if overlays:
            from efectos import grafo_overlays
            partes, final = grafo_overlays('[b]', overlays)
            grafo += partes
        texto = ';'.join(grafo)
        Path(td, 'filtro.txt').write_text(texto, encoding='utf-8')
        # filtros largos, desde un archivo (FFmpeg 7 o superior)
        fc = ['-filter_complex', texto] if len(texto) < 7000 else ['-/filter_complex', 'filtro.txt']
        _run(['ffmpeg', '-v', 'error', '-y', '-i', str(Path(video).resolve()), *entradas,
              *fc, '-map', final, '-map', '0:a:0?',
              '-r', '30', '-c:v', 'libx264', '-preset', 'medium', '-crf', '20', '-pix_fmt', 'yuv420p',
              '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart', str(Path(destino).resolve())],
             cwd=td)

"""Content Studio IA - análisis de referencias (colores, ritmo y duración).

Lee las capturas y vídeos de REFERENCIAS/ (instagram, tiktok, pinterest, otras) y mide:
  - colores dominantes (de las imágenes y de fotogramas repartidos por cada vídeo);
  - ritmo: cada cuánto cambia la imagen (cambios de plano con FFmpeg);
  - duración de los vídeos.
Con eso propone colores y estilo para la ficha de marca. No se aplica nada sin aprobación.
Solo FFmpeg y Pillow; todo en este ordenador.
"""
import colorsys
import json
import re
import statistics
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

IMAGENES = ('.jpg', '.jpeg', '.png', '.webp', '.bmp')
VIDEOS = ('.mp4', '.mov', '.m4v', '.mkv', '.webm')
UMBRAL_ESCENA = 0.30   # cuánto tiene que cambiar la imagen para contar como corte


def _run(cmd):
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                       encoding='utf-8', errors='replace')
    if p.returncode:
        raise RuntimeError(p.stderr[-1500:])
    return p.stdout, p.stderr


def buscar(carpeta):
    out = []
    for f in sorted(Path(carpeta).rglob('*')):
        if f.is_file() and f.suffix.lower() in IMAGENES + VIDEOS and not f.name.startswith('_'):
            nota = f.with_suffix('.txt')
            out.append({'archivo': f, 'tipo': 'video' if f.suffix.lower() in VIDEOS else 'imagen',
                        'red': f.parent.name if f.parent != Path(carpeta) else 'otras',
                        'nota': nota.read_text(encoding='utf-8', errors='replace').strip() if nota.exists() else ''})
    return out


# ---------------------------------------------------------------- colores

def _colores_imagen(im, n=8):
    """[(rgb, peso)] de una imagen ya reducida."""
    im = im.convert('RGB')
    im.thumbnail((200, 200))
    q = im.quantize(colors=n, method=0)  # corte de la mediana
    pal = q.getpalette()
    total = im.width * im.height
    return [((pal[i * 3], pal[i * 3 + 1], pal[i * 3 + 2]), c / total) for c, i in q.getcolors() if c]


def _fotogramas(video, carpeta, n=12):
    d = duracion(video)
    fps = max(n / max(d, 0.1), 0.05)
    _run(['ffmpeg', '-v', 'error', '-y', '-i', str(video), '-vf', f'fps={fps:.4f},scale=200:-2',
          '-frames:v', str(n), str(Path(carpeta) / 'f_%03d.png')])
    return sorted(Path(carpeta).glob('f_*.png'))


def _distancia(a, b):
    return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5


def fusionar(colores, dist=38):
    """Junta colores parecidos sumando su peso."""
    grupos = []
    for rgb, w in sorted(colores, key=lambda x: -x[1]):
        for g in grupos:
            if _distancia(g['rgb'], rgb) < dist:
                t = g['peso'] + w
                g['rgb'] = tuple(round((a * g['peso'] + b * w) / t) for a, b in zip(g['rgb'], rgb))
                g['peso'] = t
                break
        else:
            grupos.append({'rgb': rgb, 'peso': w})
    total = sum(g['peso'] for g in grupos) or 1
    for g in grupos:
        g['peso'] = round(g['peso'] / total, 4)
        g['hex'] = '#%02X%02X%02X' % g['rgb']
        h, s, v = colorsys.rgb_to_hsv(*(c / 255 for c in g['rgb']))
        g['tono'], g['saturacion'], g['brillo'] = round(h * 360), round(s, 2), round(v, 2)
    return sorted(grupos, key=lambda g: -g['peso'])


def _es_neutro(g):
    return g['saturacion'] < 0.22 or g['brillo'] < 0.30


CLARO_MIN = 0.62   # el principal es el color de la palabra destacada: tiene que ser claro para leerse sobre vídeo


def proponer_colores(paleta):
    """Principal: el color vivo y CLARO con más presencia (se escribe con él sobre el vídeo).
    Secundario: otro color vivo distinto (de tono o de brillo), que puede ser oscuro: va de marcador."""
    vivos = [g for g in paleta if not _es_neutro(g)]
    if not vivos:
        return None, None
    puntua = lambda g: g['peso'] * (0.4 + g['saturacion'])
    claros = [g for g in vivos if g['brillo'] >= CLARO_MIN]
    principal = max(claros or vivos, key=puntua)
    resto = [g for g in vivos if g is not principal]

    def distinto(g):
        dt = abs(g['tono'] - principal['tono'])
        return min(dt, 360 - dt) > 25 or abs(g['brillo'] - principal['brillo']) > 0.35
    candidatos = [g for g in resto if distinto(g) and g['peso'] > 0.02]
    secundario = max(candidatos, key=puntua) if candidatos else None
    return principal, secundario


# ---------------------------------------------------------------- ritmo

def duracion(video):
    out, _ = _run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', str(video)])
    return float(out.strip() or 0)


def cortes(video, umbral=UMBRAL_ESCENA):
    _, err = _run(['ffmpeg', '-hide_banner', '-nostats', '-i', str(video), '-an',
                   '-vf', f"scale=320:-2,select='gt(scene,{umbral})',showinfo", '-f', 'null', '-'])
    return [float(x) for x in re.findall(r'pts_time:([\d.]+)', err)]


def estilo_por_ritmo(seg_por_plano):
    if seg_por_plano is None:
        return None
    if seg_por_plano < 2.0:
        return 'muy_dinamico'
    if seg_por_plano <= 5.0:
        return 'dinamico'
    return 'sobrio'


# ---------------------------------------------------------------- todo

def analizar(carpeta, aviso=print):
    from PIL import Image
    refs = buscar(carpeta)
    if not refs:
        return None
    todos, por_archivo, planos, duraciones = [], [], [], []
    with tempfile.TemporaryDirectory() as td:
        for i, r in enumerate(refs):
            aviso(f'  Analizando {r["red"]}/{r["archivo"].name}...')
            info = {'archivo': f'{r["red"]}/{r["archivo"].name}', 'tipo': r['tipo'], 'nota': r['nota']}
            try:
                if r['tipo'] == 'imagen':
                    with Image.open(r['archivo']) as im:
                        cols = _colores_imagen(im)
                else:
                    sub = Path(td) / f'v{i}'
                    sub.mkdir()
                    cols = []
                    frames = _fotogramas(r['archivo'], sub)
                    for f in frames:
                        with Image.open(f) as im:
                            cols += [(c, w / len(frames)) for c, w in _colores_imagen(im)]
                    d = duracion(r['archivo'])
                    cs = cortes(r['archivo'])
                    seg = d / (len(cs) + 1)
                    info.update({'duracion_s': round(d, 1), 'cambios_de_plano': len(cs),
                                 'segundos_por_plano': round(seg, 2)})
                    planos.append(seg)
                    duraciones.append(d)
            except Exception as e:
                info['error'] = str(e)[:300]
                por_archivo.append(info)
                continue
            # cada referencia pesa lo mismo, sea imagen o vídeo
            total = sum(w for _, w in cols) or 1
            todos += [(c, w / total) for c, w in cols]
            info['colores'] = [g['hex'] for g in fusionar(cols)[:4]]
            por_archivo.append(info)
    paleta = fusionar(todos)[:8]
    principal, secundario = proponer_colores(paleta)
    seg = statistics.median(planos) if planos else None
    return {
        'fecha': datetime.now().isoformat(timespec='seconds'),
        'referencias': por_archivo,
        'paleta': paleta,
        'propuesta': {
            'principal': principal['hex'] if principal else None,
            'secundario': secundario['hex'] if secundario else None,
            'segundos_por_plano': round(seg, 2) if seg else None,
            'estilo': estilo_por_ritmo(seg),
            'duracion_tipica_s': round(statistics.median(duraciones)) if duraciones else None,
        },
    }


def imagen_paleta(paleta, destino):
    """Muestra numerada de la paleta, para elegir viendo."""
    from PIL import Image, ImageDraw, ImageFont
    w, h = 180, 220
    im = Image.new('RGB', (w * len(paleta), h), 'white')
    d = ImageDraw.Draw(im)
    try:
        f = ImageFont.truetype('arialbd.ttf', 26)
        f2 = ImageFont.truetype('arial.ttf', 20)
    except Exception:
        f = f2 = ImageFont.load_default()
    for i, g in enumerate(paleta):
        d.rectangle([i * w, 0, (i + 1) * w - 4, 150], fill=g['rgb'])
        d.text((i * w + 10, 160), f'{i + 1}. {g["hex"]}', fill='black', font=f)
        d.text((i * w + 10, 192), f'{round(g["peso"] * 100)} %', fill=(90, 90, 90), font=f2)
    im.save(destino)


def muestra_estilo(video, estilo_subs, destino, filtro_vertical='', segundo=1.0):
    """Un fotograma del vídeo de la usuaria con un subtítulo de ejemplo en el estilo propuesto."""
    import subtitulos as st
    with tempfile.TemporaryDirectory() as td:
        subs = [{'inicio': 0.0, 'fin': 99.0, 'palabras': [
            {'w': 'mira', 'start': 0, 'end': 1}, {'w': 'tus', 'start': 0, 'end': 1},
            {'w': 'subtítulos', 'start': 0, 'end': 1, 'destacada': True}]}]
        e = dict(estilo_subs)
        e['max_palabras'] = 3
        st.generar_ass(subs, e, Path(td) / 'subs.ass')
        vf = ','.join(x for x in (filtro_vertical, 'subtitles=subs.ass') if x)
        p = subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', f'{segundo:.2f}', '-i', str(Path(video).resolve()),
                            '-frames:v', '1', '-vf', vf, str(Path(destino).resolve())],
                           cwd=td, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                           encoding='utf-8', errors='replace')
        if p.returncode:
            raise RuntimeError(p.stderr[-1000:])

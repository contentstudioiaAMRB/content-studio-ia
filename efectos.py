"""Content Studio IA - efectos y pegatinas (etapa 2).

- Zoom: el plano cambia de tamaño en cada corte (salto de cámara) y se acerca un poco
  en las palabras destacadas.
- Destello: un brillo muy corto en cada corte (opcional).
- Pegatinas: emojis con borde blanco (o tus PNG de recursos/pegatinas) que aparecen
  cuando dices ciertas palabras (lista editable en marca/pegatinas.json).
Todo con FFmpeg; las pegatinas de emoji se dibujan con Pillow.
"""
import json
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

ANCHO, ALTO, FPS = 1080, 1920, 30

PEGATINAS_POR_DEFECTO = {
    'regal': '🎁', 'navidad': '🎄', 'navideñ': '🎄', 'calendario': '📅', 'sorpresa': '🎉',
    'encanta': '💕', 'amor': '💕', 'obsesionad': '😍', 'belleza': '💄', 'maquillaje': '💄',
    'labial': '💋', 'precios': '✨', 'bonit': '✨', 'divin': '✨', 'favorit': '⭐',
    'comenten': '💬', 'comenta': '💬', 'link': '🔗', 'piel': '🧴', 'crema': '🧴',
    'perfume': '🌸', 'dinero': '💰', 'oferta': '🏷️', 'nuevo': '🆕', 'adios': '👋',
    'hola': '👋', 'feliz': '🥳', 'viaje': '✈️', 'cafe': '☕', 'ojo': '👀', 'miren': '👀',
}

FUENTE_EMOJI = {
    'win32': r'C:\Windows\Fonts\seguiemj.ttf',
    'darwin': '/System/Library/Fonts/Apple Color Emoji.ttc',
}.get(sys.platform, '/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf')


def _limpia(w):
    w = unicodedata.normalize('NFKD', w.lower())
    return re.sub(r'[^a-z0-9ñ]', '', ''.join(c for c in w if not unicodedata.combining(c)))


# ---------------------------------------------------------------- pegatinas

def crear_pegatina(emoji, destino, tam=230, giro=0):
    """Dibuja un emoji en color con borde blanco y sombra suave, como un sticker."""
    from PIL import Image, ImageDraw, ImageFilter, ImageFont
    size = 109 if sys.platform == 'darwin' else 200   # la letra de Apple solo trae 109 px
    f = ImageFont.truetype(FUENTE_EMOJI, size)
    lienzo = Image.new('RGBA', (size * 3, size * 2), (0, 0, 0, 0))
    ImageDraw.Draw(lienzo).text((size // 2, size // 3), emoji, font=f, embedded_color=True)
    caja = lienzo.getbbox()
    if not caja:
        raise RuntimeError(f'No se puede dibujar el emoji {emoji}')
    em = lienzo.crop(caja)
    em = em.resize((tam, round(em.height * tam / em.width)), Image.LANCZOS)
    borde = 14
    w, h = em.width + borde * 4, em.height + borde * 4
    alfa = Image.new('L', (w, h), 0)
    alfa.paste(em.getchannel('A'), (borde * 2, borde * 2))
    contorno = alfa.point(lambda a: 255 if a > 40 else 0)
    for _ in range(borde // 2):
        contorno = contorno.filter(ImageFilter.MaxFilter(5))
    sombra = contorno.filter(ImageFilter.GaussianBlur(8)).point(lambda a: a * 0.35)
    out = Image.new('RGBA', (w + 8, h + 8), (0, 0, 0, 0))
    out.paste(Image.new('RGBA', (w, h), (0, 0, 0, 255)), (6, 8), sombra)
    out.paste(Image.new('RGBA', (w, h), (255, 255, 255, 255)), (0, 0), contorno)
    out.alpha_composite(em, (borde * 2, borde * 2))
    if giro:
        out = out.rotate(giro, resample=Image.BICUBIC, expand=True)
    out.save(destino)
    return out.size


def cargar_lista(ruta_json):
    lista = dict(PEGATINAS_POR_DEFECTO)
    if ruta_json and Path(ruta_json).exists():
        lista.update(json.loads(Path(ruta_json).read_text(encoding='utf-8')))
    elif ruta_json:
        Path(ruta_json).write_text(json.dumps(lista, ensure_ascii=False, indent=1), encoding='utf-8')
    return {_limpia(k): v for k, v in lista.items() if _limpia(k)}


def elegir_pegatinas(subs, lista, carpeta_png=None, dur=1.6, separacion=1.2, maximo=8):
    """Una pegatina cuando se dice una palabra de la lista; nunca dos a la vez."""
    pngs = {}
    if carpeta_png and Path(carpeta_png).is_dir():
        pngs = {_limpia(p.stem): p for p in Path(carpeta_png).glob('*.png')}
    elegidas, libre, lado = [], 0.0, 0
    for s in subs:
        for p in s['palabras']:
            w = _limpia(p['w'])
            if not w or p['start'] < libre or len(elegidas) >= maximo:
                continue
            png = next((v for k, v in pngs.items() if w.startswith(k)), None)
            emoji = None if png else next((v for k, v in lista.items() if w.startswith(k)), None)
            if png or emoji:
                elegidas.append({'inicio': p['start'], 'fin': p['start'] + dur, 'palabra': p['w'],
                                 'png': str(png) if png else None, 'emoji': emoji, 'lado': lado})
                lado = 1 - lado
                libre = p['start'] + dur + separacion
    return elegidas


# ---------------------------------------------------------------- zoom y destellos

def expr_zoom(cortes_s, subs, zoom_corte=1.08, zoom_palabra=1.12):
    """Zoom por tramos alternos (salto de cámara en cada corte) y acercamiento en palabras destacadas."""
    partes = []
    bordes = [0.0] + list(cortes_s)
    for i in range(1, len(bordes), 2):   # tramos impares, un poco más cerca
        fin = bordes[i + 1] if i + 1 < len(bordes) else 99999
        partes.append(f'between(it,{bordes[i]:.3f},{fin:.3f})*{zoom_corte - 1:.3f}')
    base = '+'.join(partes) or '0'
    golpes = []
    for s in subs:
        if any(p.get('destacada') for p in s['palabras']):
            a, b = s['inicio'], s['fin']
            # entra en 0,12 s y se mantiene mientras dura el subtítulo
            golpes.append(f'between(it,{a:.3f},{b:.3f})*min(1,(it-{a:.3f})/0.12)')
    punch = '+'.join(golpes) or '0'
    return f'1+({base})+({punch})*{zoom_palabra - 1:.3f}'


def expr_destello(cortes_s, intensidad=0.22, dur=0.12):
    if not cortes_s:
        return '0'
    return '+'.join(f'between(t,{c:.3f},{c + dur:.3f})*{intensidad}*(1-(t-{c:.3f})/{dur})' for c in cortes_s)


def cortes_desde_json(cortes_json):
    """Momentos de corte en el vídeo cortado (fin de cada tramo conservado menos el último)."""
    if not cortes_json or not Path(cortes_json).exists():
        return []
    tramos = json.loads(Path(cortes_json).read_text(encoding='utf-8')).get('tramos_conservados_s', [])
    t, out = 0.0, []
    for a, b in tramos[:-1]:
        t += b - a
        out.append(round(t, 3))
    return out


# ---------------------------------------------------------------- todo junto

def construir(subs, cortes_s, opciones, carpeta_trabajo, lista_pegatinas, carpeta_png):
    """Devuelve (entradas_extra, cadena_base, overlays, pegatinas) para el filtro de FFmpeg.
    cadena_base va después del paso a vertical y antes de los subtítulos."""
    cadena = []
    if opciones.get('zoom'):
        z = expr_zoom(cortes_s, subs)
        cadena.append(f"zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih*0.4-(ih/zoom*0.4)'"
                      f":d=1:s={ANCHO}x{ALTO}:fps={FPS}")
    if opciones.get('destellos') and cortes_s:
        cadena.append(f"eq=brightness='{expr_destello(cortes_s)}':eval=frame")
    entradas, overlays, peg = [], [], []
    if opciones.get('pegatinas'):
        peg = elegir_pegatinas(subs, lista_pegatinas, carpeta_png)
        for i, p in enumerate(peg):
            if p['png']:
                ruta = p['png']
                from PIL import Image
                with Image.open(ruta) as im:
                    w, h = im.size
                if w > 300:
                    h, w = round(h * 300 / w), 300
            else:
                ruta = str(Path(carpeta_trabajo) / f'pegatina_{i}.png')
                w, h = crear_pegatina(p['emoji'], ruta, giro=(-10 if p['lado'] == 0 else 10))
            x = 70 if p['lado'] == 0 else ANCHO - 70 - w
            y = 300 if p['lado'] == 0 else 360
            dur = p['fin'] - p['inicio']
            entradas += ['-loop', '1', '-framerate', str(FPS), '-t', f'{dur:.3f}', '-i', ruta]
            overlays.append({'w': w, 'h': h, 'x': x, 'y': y, 'inicio': p['inicio'], 'dur': dur})
    return entradas, ','.join(cadena), overlays, peg


def grafo_overlays(base_label, overlays, primer_indice=1):
    partes, actual = [], base_label
    for i, o in enumerate(overlays):
        idx = primer_indice + i
        a, d = o['inicio'], o['dur']
        partes.append(f"[{idx}:v]scale={o['w']}:{o['h']},format=rgba,"
                      f"fade=in:st=0:d=0.15:alpha=1,fade=out:st={max(0.0, d - 0.2):.3f}:d=0.2:alpha=1,"
                      f"setpts=PTS+{a:.3f}/TB[pg{i}]")
        sig = f'[o{i}]'
        partes.append(f"{actual}[pg{i}]overlay=x={o['x']}:y='{o['y']}+50*max(0,1-(t-{a:.3f})/0.18)'"
                      f":eof_action=pass{sig}")
        actual = sig
    return partes, actual

"""Content Studio IA - ficha de marca por usuaria.

Cada usuaria tiene su ficha en marca/perfiles/<nombre>.json y la activa se apunta
en marca/activa.txt. La ficha se configura una vez y se aplica sola a los cortes,
los subtítulos y los efectos de todos sus vídeos.
"""
import copy
import json
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent

try:   # si las respuestas llegan por tubería (pruebas), que las tildes se lean bien
    if not sys.stdin.isatty():
        sys.stdin.reconfigure(encoding='utf-8')
except Exception:
    pass
CARPETA = ROOT / 'marca' / 'perfiles'
ACTIVA = ROOT / 'marca' / 'activa.txt'
FUENTES_PROPIAS = ROOT / 'recursos' / 'fuentes'

PLANTILLA = {
    'nombre': '',
    'nicho': '',
    'colores': {'principal': '#E8C77A', 'secundario': '#7A1F24', 'texto': '#FFFFFF'},
    'tipografias': {'subtitulos': 'Poppins', 'destacado': ''},
    'subtitulos': {
        'tamano': 80,              # píxeles sobre 1080x1920
        'posicion': 'pecho',       # pecho | centro | abajo
        'mayusculas': 'minusculas',  # minusculas | mayusculas | normal
        'palabras': 3,             # palabras por subtítulo (1-3)
        'borde': 'sombra',         # sombra | contorno | ninguno
        'destacado': 'color',      # color (palabra en el color principal) | marcador (borde grueso del secundario)
    },
    'destacar': {'palabras': [], 'automatico': True},
    'estilo': 'dinamico',          # sobrio | dinamico | muy_dinamico
    'vertical': 'recortar',        # recortar | rellenar
    'pegatinas_extra': {},         # palabra -> emoji, además de la lista general
}

ESTILOS = {
    'sobrio': ('Sobrio: cortes limpios y subtítulos, sin efectos',
               {'zoom': False, 'pegatinas': False, 'destellos': False}),
    'dinamico': ('Dinámico: zoom en los cortes y palabras clave, y pegatinas',
                 {'zoom': True, 'pegatinas': True, 'destellos': False}),
    'muy_dinamico': ('Muy dinámico: lo anterior y un destello en cada corte',
                     {'zoom': True, 'pegatinas': True, 'destellos': True}),
}

COLORES_NOMBRE = {
    'blanco': '#FFFFFF', 'negro': '#000000', 'dorado': '#E8C77A', 'oro': '#E8C77A',
    'amarillo': '#FFD21F', 'rojo': '#D7263D', 'vino': '#7A1F24', 'granate': '#7A1F24',
    'rosa': '#FF6FA8', 'rosa palo': '#F4C2C2', 'fucsia': '#E5007E', 'morado': '#8E44AD',
    'lila': '#C3A6E0', 'azul': '#2D6CDF', 'celeste': '#7EC8F2', 'verde': '#2BB673',
    'menta': '#9FE2BF', 'naranja': '#FF8A00', 'beige': '#E8D9C5', 'crema': '#F3E6D8',
    'nude': '#E3BC9A', 'gris': '#9AA0A6', 'plateado': '#C0C0C0',
}


# ---------------------------------------------------------------- utilidades

def _slug(texto):
    t = unicodedata.normalize('NFKD', texto.lower())
    t = ''.join(c for c in t if not unicodedata.combining(c))
    return re.sub(r'[^a-z0-9]+', '-', t).strip('-') or 'usuaria'


def _fusionar(base, extra):
    out = copy.deepcopy(base)
    for k, v in (extra or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _fusionar(out[k], v)
        else:
            out[k] = v
    return out


def color(valor, actual):
    """Acepta #RRGGBB, RRGGBB o un nombre (dorado, rosa...). Si no lo entiende, deja el actual."""
    v = (valor or '').strip().lower()
    if not v:
        return actual
    if v in COLORES_NOMBRE:
        return COLORES_NOMBRE[v]
    v = v.lstrip('#')
    if re.fullmatch(r'[0-9a-f]{6}', v):
        return '#' + v.upper()
    if re.fullmatch(r'[0-9a-f]{3}', v):
        return '#' + ''.join(c * 2 for c in v).upper()
    print(f'  No entiendo el color «{valor}». Se queda {actual}.')
    return actual


_FUENTES = None


def fuentes_instaladas():
    """{nombre de familia en minúsculas: nombre bonito} de las letras del ordenador y de recursos/fuentes."""
    global _FUENTES
    if _FUENTES is not None:
        return _FUENTES
    from PIL import ImageFont
    import os
    carpetas = [FUENTES_PROPIAS]
    if sys.platform == 'win32':
        carpetas += [Path(os.environ.get('WINDIR', r'C:\Windows')) / 'Fonts',
                     Path(os.environ.get('LOCALAPPDATA', '')) / 'Microsoft' / 'Windows' / 'Fonts']
    elif sys.platform == 'darwin':
        carpetas += [Path('/Library/Fonts'), Path('/System/Library/Fonts'), Path.home() / 'Library' / 'Fonts']
    else:
        carpetas += [Path('/usr/share/fonts'), Path.home() / '.local' / 'share' / 'fonts']
    _FUENTES = {}
    for c in carpetas:
        if not c.is_dir():
            continue
        for f in c.rglob('*'):
            if f.suffix.lower() in ('.ttf', '.otf', '.ttc'):
                try:
                    fam = ImageFont.truetype(str(f), 12).font.family
                    if fam:
                        _FUENTES.setdefault(fam.lower(), fam)
                except Exception:
                    pass
    return _FUENTES


def comprobar_fuente(nombre):
    """Devuelve el nombre exacto si está instalada; si no, None y sugerencias."""
    fs = fuentes_instaladas()
    if nombre.lower() in fs:
        return fs[nombre.lower()], []
    parecidas = [v for k, v in fs.items() if nombre.lower()[:4] in k][:6]
    return None, parecidas


# ---------------------------------------------------------------- perfiles

def listar():
    CARPETA.mkdir(parents=True, exist_ok=True)
    return sorted(CARPETA.glob('*.json'))


def cargar(ruta):
    return _fusionar(PLANTILLA, json.loads(Path(ruta).read_text(encoding='utf-8')))


def guardar(perfil):
    CARPETA.mkdir(parents=True, exist_ok=True)
    ruta = CARPETA / f"{_slug(perfil['nombre'])}.json"
    ruta.write_text(json.dumps(perfil, ensure_ascii=False, indent=2), encoding='utf-8')
    ACTIVA.write_text(ruta.name, encoding='utf-8')
    return ruta


def activo():
    """La ficha de la usuaria activa, o None si todavía no hay ninguna."""
    perfiles = listar()
    if not perfiles:
        return None
    nombre = ACTIVA.read_text(encoding='utf-8').strip() if ACTIVA.exists() else ''
    ruta = CARPETA / nombre if nombre and (CARPETA / nombre).exists() else perfiles[0]
    return cargar(ruta)


def activar(ruta):
    ACTIVA.write_text(Path(ruta).name, encoding='utf-8')


def efectos(perfil):
    return dict(ESTILOS.get(perfil.get('estilo'), ESTILOS['dinamico'])[1])


def estilo_subtitulos(perfil):
    """Traduce la ficha al estilo que usa subtitulos.py."""
    s, c, t = perfil['subtitulos'], perfil['colores'], perfil['tipografias']
    return {
        'fuente': t['subtitulos'] or 'Arial',
        'negrita': True,
        'fuente_destacado': t.get('destacado', ''),
        'tamano': int(s['tamano']),
        'color': c.get('texto', '#FFFFFF'),
        'color_destacado': c['principal'],
        'color_marcador': c.get('secundario') or c['principal'],
        'destacado': s.get('destacado', 'color'),
        'mayusculas': s['mayusculas'],
        'contorno': s['borde'],
        'posicion': s['posicion'],
        'max_palabras': int(s['palabras']),
    }


def resumen(p):
    s, c, t = p['subtitulos'], p['colores'], p['tipografias']
    dest = ', '.join(p['destacar']['palabras']) or '—'
    return '\n'.join([
        f"  Nombre: {p['nombre']}   ·   Nicho: {p['nicho'] or '—'}",
        f"  Colores: principal {c['principal']} · secundario {c['secundario']} · texto {c['texto']}",
        f"  Letras: subtítulos {t['subtitulos']} · destacado {t['destacado'] or '(la misma)'}",
        f"  Subtítulos: {s['tamano']} px · {s['posicion']} · {s['mayusculas']} · {s['palabras']} palabra(s) · "
        f"borde {s['borde']} · destacado con {s['destacado']}",
        f"  Palabras que siempre se destacan: {dest}"
        f"{'  (+ automáticas)' if p['destacar']['automatico'] else ''}",
        f"  Estilo de vídeo: {ESTILOS[p['estilo']][0]}",
        f"  Paso a vertical: {p['vertical']}",
    ])


# ---------------------------------------------------------------- asistente

def _opcion(ask, pregunta, opciones, actual):
    claves = list(opciones)
    print(pregunta)
    for i, k in enumerate(claves, 1):
        print(f'   {i}. {opciones[k]}')
    r = ask('  Elige', str(claves.index(actual) + 1 if actual in claves else 1))
    try:
        return claves[int(r) - 1]
    except (ValueError, IndexError):
        return actual


def _fuente(ask, pregunta, actual, vacia_ok=False):
    while True:
        r = ask(pregunta, actual)
        if vacia_ok and r in ('', '-'):
            return ''
        exacta, parecidas = comprobar_fuente(r)
        if exacta:
            return exacta
        print(f'  La letra «{r}» no está instalada en este ordenador'
              + (f'. Parecidas: {", ".join(parecidas)}' if parecidas else '')
              + '. Puedes poner su archivo .ttf en recursos/fuentes o elegir otra.')
        if ask('  ¿Usarla igualmente? (s/n)', 'n').lower() == 's':
            return r


def asistente(ask, perfil=None):
    p = copy.deepcopy(perfil) if perfil else copy.deepcopy(PLANTILLA)
    print('\nMI MARCA — se configura una vez y se aplica sola a todos tus vídeos (Enter = dejar como está)\n')
    while True:
        p['nombre'] = ask('1. Tu nombre (como quieres que te conozcan)', p['nombre'])
        if p['nombre']:
            break
    p['nicho'] = ask('2. Tu nicho (ej.: belleza, moda, fitness, negocio)', p['nicho'])

    print('\n3. Colores (escribe un nombre como dorado, rosa, vino, o un código como #E8C77A)')
    p['colores']['principal'] = color(ask('   Principal: el de las palabras destacadas', p['colores']['principal']), p['colores']['principal'])
    p['colores']['secundario'] = color(ask('   Secundario: para detalles y el marcador', p['colores']['secundario']), p['colores']['secundario'])
    p['colores']['texto'] = color(ask('   Color del texto de los subtítulos', p['colores']['texto']), p['colores']['texto'])

    print('\n4. Tipografías')
    p['tipografias']['subtitulos'] = _fuente(ask, '   Letra de los subtítulos (ej.: Poppins, Montserrat, Arial)',
                                             p['tipografias']['subtitulos'])
    p['tipografias']['destacado'] = _fuente(ask, '   Letra de la palabra destacada (Enter o «-» = la misma)',
                                            p['tipografias']['destacado'], vacia_ok=True)

    s = p['subtitulos']
    print()
    s['tamano'] = _opcion(ask, '5. Tamaño de los subtítulos', {64: 'Pequeño (64 px)', 80: 'Medio (80 px)',
                                                               96: 'Grande (96 px)', 112: 'Muy grande (112 px)'},
                          int(s['tamano']))
    s['posicion'] = _opcion(ask, '6. Posición', {'pecho': 'A la altura del pecho (recomendado: no tapa la cara)',
                                                 'centro': 'Centro de la pantalla',
                                                 'abajo': 'Abajo (por encima del texto de Instagram/TikTok)'},
                            s['posicion'])
    s['mayusculas'] = _opcion(ask, '7. Letras', {'minusculas': 'minúsculas', 'mayusculas': 'MAYÚSCULAS',
                                                 'normal': 'Como se dicen'}, s['mayusculas'])
    s['palabras'] = _opcion(ask, '8. Palabras por subtítulo', {1: 'Una', 2: 'Hasta dos', 3: 'Hasta tres'},
                            int(s['palabras']))
    s['borde'] = _opcion(ask, '9. Borde del texto', {'sombra': 'Sombra suave', 'contorno': 'Contorno negro',
                                                     'ninguno': 'Nada'}, s['borde'])
    s['destacado'] = _opcion(ask, '10. Cómo se marca la palabra destacada',
                             {'color': 'En tu color principal', 'marcador': 'Con un borde grueso de tu color secundario'},
                             s['destacado'])

    r = ask('\n11. Palabras que quieres destacar SIEMPRE, separadas por comas (ej.: Farmasi, regalo; «-» = ninguna)',
            ', '.join(p['destacar']['palabras']))
    p['destacar']['palabras'] = [] if r.strip() == '-' else [x.strip() for x in r.split(',') if x.strip()]
    p['destacar']['automatico'] = ask('    ¿Además destaco yo otras palabras importantes? (s/n)',
                                      's' if p['destacar']['automatico'] else 'n').lower() == 's'

    print()
    p['estilo'] = _opcion(ask, '12. Estilo general de tus vídeos', {k: v[0] for k, v in ESTILOS.items()}, p['estilo'])
    p['vertical'] = _opcion(ask, '13. Si un vídeo está en horizontal', {
        'recortar': 'Recortarlo para llenar la pantalla', 'rellenar': 'Verlo completo con fondo difuminado'},
        p['vertical'])

    print('\nASÍ QUEDA TU MARCA:\n' + resumen(p))
    if ask('\n¿La guardo? (s/n)', 's').lower() != 's':
        print('No se ha guardado nada.')
        return None
    ruta = guardar(p)
    print(f'Guardada en marca/perfiles/{ruta.name}. Se aplicará sola a tus próximos vídeos.')
    return p

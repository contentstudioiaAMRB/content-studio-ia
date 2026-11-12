"""Prueba de exportación de Content Studio IA. No usa vídeos de nadie ni internet.

Crea un vídeo sintético (horizontal, con un silencio en medio) y lo pasa por el programa de verdad:
ficha de marca de ejemplo -> cortar silencios -> vertical 1080x1920 -> subtítulos con tipografías de la
marca -> zoom, destellos y pegatinas -> MP4. Después comprueba el resultado (tamaño, códecs, duración,
que los subtítulos se ven en la imagen con el color de la marca y que libass usa las letras incluidas)
y analiza unas referencias sintéticas. Lo borra todo al terminar.

El reconocimiento de voz no se prueba aquí (necesitaría una voz real y el modelo de 1,6 GB): se le dan
las palabras ya escritas. Si el modelo ya está descargado, se comprueba que carga.

Uso: <python del programa> instalador/prueba_exportacion.py [--conservar]
  --conservar  deja el vídeo de prueba en salida/ para verlo.
Termina con «RESULTADO: OK» (código 0) o «RESULTADO: FALLA ...» (código 1).
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

import content_studio as cs   # noqa: E402  (también pone el FFmpeg completo en el PATH en Mac)
import efectos as fx           # noqa: E402
import marca                   # noqa: E402
import referencias as rf       # noqa: E402
import subtitulos as st        # noqa: E402

FICHA = ROOT / 'plantillas' / 'marca_ejemplo.json'
fallos = []


def paso(nombre, bien, detalle=''):
    if not bien:
        fallos.append(nombre)
    print(f"  [{'  OK  ' if bien else 'FALLA '}] {nombre}{(' — ' + str(detalle)) if detalle != '' else ''}",
          flush=True)
    return bien


def ff(*args, cwd=None):
    p = subprocess.run(['ffmpeg', '-hide_banner', *args], capture_output=True, text=True,
                       encoding='utf-8', errors='replace', cwd=cwd)
    if p.returncode:
        raise RuntimeError(p.stderr[-1500:])
    return p.stderr


def sondear(video):
    out = subprocess.run(['ffprobe', '-v', 'error', '-show_entries',
                          'stream=codec_type,codec_name,width,height:format=duration', '-of', 'json', str(video)],
                         capture_output=True, text=True, encoding='utf-8', errors='replace').stdout
    j = json.loads(out)
    v = next((s for s in j['streams'] if s['codec_type'] == 'video'), {})
    a = next((s for s in j['streams'] if s['codec_type'] == 'audio'), {})
    return v, a, float(j.get('format', {}).get('duration', 0) or 0)


def pixeles_parecidos(png, rgb, tol=40, zona=None):
    from PIL import Image
    with Image.open(png) as im:
        im = im.convert('RGB')
        if zona:
            im = im.crop(zona)
        r0, g0, b0 = rgb
        datos = im.get_flattened_data() if hasattr(im, 'get_flattened_data') else im.getdata()
        return sum(1 for r, g, b in datos if abs(r - r0) < tol and abs(g - g0) < tol and abs(b - b0) < tol)


def fotograma(video, segundo, destino):
    ff('-v', 'error', '-y', '-ss', f'{segundo:.2f}', '-i', str(video), '-frames:v', '1', str(destino))
    return destino


def main(conservar=False):
    t0 = time.time()
    print('\nPRUEBA DE EXPORTACIÓN DE CONTENT STUDIO IA\n', flush=True)
    if not cs.herramientas_ok():
        print('RESULTADO: FALLA no se encuentra FFmpeg/FFprobe')
        return 1
    td = Path(tempfile.mkdtemp(prefix='csia_prueba_'))
    cs.SALIDA = td                      # nada de la prueba va a la carpeta salida/ de la usuaria
    original_cargar_lista = fx.cargar_lista
    fx.cargar_lista = lambda ruta: original_cargar_lista(None)   # no crea marca/pegatinas.json
    try:
        # ------------------------------------------------ 1. ficha de marca
        perfil = marca.cargar(FICHA)
        estilo = marca.estilo_subtitulos(perfil)
        paso('Ficha de marca de ejemplo', perfil['nombre'] == 'Marca de prueba',
             f"estilo {perfil['estilo']}, vertical {perfil['vertical']}")
        for letra in (perfil['tipografias']['subtitulos'], perfil['tipografias']['destacado']):
            exacta, _ = marca.comprobar_fuente(letra)
            paso(f'Tipografía «{letra}» disponible', bool(exacta), exacta or 'no encontrada')

        # ------------------------------------------------ 2. vídeo sintético (horizontal, silencio 2,0-3,4 s)
        bruto = td / 'bruto_sintetico.mp4'
        ff('-v', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc2=size=1920x1080:rate=30:duration=6',
           '-f', 'lavfi', '-i', "aevalsrc='0.4*sin(2*PI*330*t)*(lt(t,2)+gte(t,3.4))':s=48000:d=6",
           '-c:v', 'libx264', '-preset', 'veryfast', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest', str(bruto))
        v, a, d = sondear(bruto)
        paso('Vídeo sintético creado', d > 5.5 and v.get('width') == 1920, f'{v.get("width")}x{v.get("height")}, {d:.1f} s')

        # ------------------------------------------------ 3. cortar silencios + vertical
        silencios, umbral = cs.detectar_silencios(bruto)
        cortes = cs.proponer_cortes(silencios, cs.info_video(bruto)['duracion'])
        paso('Detecta el silencio', len(cortes) >= 1,
             ', '.join(f"{c['inicio']:.2f}-{c['fin']:.2f} s" for c in cortes) + f' (umbral {umbral} dB)')
        cortado, informe = cs.exportar_cortado(bruto, cortes, perfil['vertical'], destino=td / 'cortado.mp4')
        v, a, d = sondear(cortado)
        paso('Exporta el corte en vertical 1080x1920',
             (v.get('width'), v.get('height')) == (1080, 1920) and a.get('codec_name') == 'aac',
             f"{v.get('width')}x{v.get('height')}, {d:.2f} s (antes {informe['duracion_original_s']:.2f} s)")
        paso('El corte acorta el vídeo', d < informe['duracion_original_s'] - 0.8, f'{d:.2f} s')

        # ------------------------------------------------ 4. subtítulos, tipografías, efectos y pegatinas
        palabras = [('Hola', 0.20, 0.60), ('chicas,', 0.65, 1.10), ('hoy', 1.30, 1.50), ('les', 1.55, 1.70),
                    ('traigo', 1.75, 2.10), ('un', 2.20, 2.30), ('regalo', 2.35, 2.90), ('precioso.', 3.00, 3.60)]
        st.transcribir = lambda *a_, **k_: [{'w': w, 'start': s, 'end': e} for w, s, e in palabras]
        final, srt, inf = cs.subtitular(cortado, perfil=perfil, aviso=lambda *a_: None)
        v, a, d = sondear(final)
        paso('Exporta el vídeo final (MP4 H.264 + AAC)',
             v.get('codec_name') == 'h264' and a.get('codec_name') == 'aac' and final.stat().st_size > 50_000,
             f"{final.name}, {final.stat().st_size // 1024} KB")
        paso('Final en 1080x1920', (v.get('width'), v.get('height')) == (1080, 1920), f"{v.get('width')}x{v.get('height')}")
        paso('Duración del final igual a la del corte', abs(d - sondear(cortado)[2]) < 0.15, f'{d:.2f} s')
        paso('Subtítulos SRT', srt.exists() and 'regalo' in srt.read_text(encoding='utf-8'))
        paso('Palabra destacada de la marca', 'regalo' in inf['destacadas'], ', '.join(inf['destacadas']))
        paso('Efectos del estilo «muy dinámico»', inf['efectos'] == {'zoom': True, 'pegatinas': True, 'destellos': True}
             and len(inf['cortes_en_el_video_s']) >= 1, f"{inf['efectos']}, cortes en {inf['cortes_en_el_video_s']}")
        paso('Pegatinas', len(inf['pegatinas']) >= 1,
             ', '.join(f"{p['pegatina']} en «{p['palabra']}» ({p['segundo']} s)" for p in inf['pegatinas']))

        # el subtítulo destacado se ve: píxeles del color principal (#FF6FA8) en la zona del texto
        rgb = tuple(int(perfil['colores']['principal'].lstrip('#')[i:i + 2], 16) for i in (0, 2, 4))
        zona = (0, 1000, 1080, 1500)
        con = pixeles_parecidos(fotograma(final, 2.6, td / 'f_final.png'), rgb, zona=zona)
        sin = pixeles_parecidos(fotograma(cortado, 2.6, td / 'f_cortado.png'), rgb, zona=zona)
        paso('Los subtítulos se ven en la imagen (color de la marca)', con > 400 and con > sin * 3,
             f'{con} píxeles del color principal (sin subtítulos: {sin})')

        # libass usa las tipografías incluidas (no una letra de sustitución del sistema)
        fdir = td / 'fuentes'
        fdir.mkdir()
        for f in cs.FUENTES.glob('*.ttf'):
            shutil.copy(f, fdir / f.name)
        ass = td / 'letras.ass'
        st.generar_ass([{'inicio': 0, 'fin': 1, 'palabras': [{'w': 'prueba'}, {'w': 'regalo', 'destacada': True}]}],
                       estilo, ass)
        log = ff('-v', 'verbose', '-f', 'lavfi', '-i', 'color=c=black:s=1080x1920:d=1', '-vf',
                 'subtitles=letras.ass:fontsdir=fuentes', '-frames:v', '1', '-f', 'null', '-', cwd=td)
        elegidas = [l.split('fontselect:')[1].strip() for l in log.splitlines() if 'fontselect:' in l]
        for letra in (estilo['fuente'], estilo['fuente_destacado']):
            linea = next((e for e in elegidas if e.startswith(f'({letra},')), '')
            usa = linea.split('->')[-1].replace(' ', '').lower() if '->' in linea else ''
            paso(f'libass dibuja con «{letra}»', letra.replace(' ', '').lower() in usa, linea or 'no la ha pedido')

        # ------------------------------------------------ 5. referencias (colores y ritmo)
        ref = td / 'REFERENCIAS'
        (ref / 'otras').mkdir(parents=True)
        from PIL import Image
        im = Image.new('RGB', (400, 400), (255, 111, 168))
        im.paste((40, 40, 120), (0, 250, 400, 400))
        im.save(ref / 'otras' / 'captura.png')
        ff('-v', 'error', '-y', '-f', 'lavfi', '-i', 'color=c=0xFF6FA8:s=360x640:d=1.5', '-f', 'lavfi',
           '-i', 'color=c=0x283C78:s=360x640:d=1.5', '-filter_complex', '[0][1]concat=n=2:v=1[v]', '-map', '[v]',
           '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(ref / 'otras' / 'reel.mp4'))
        an = rf.analizar(ref, aviso=lambda *a_: None)
        prop = (an or {}).get('propuesta', {})
        paso('Analiza referencias (colores y ritmo)', bool(an and an['paleta'] and prop.get('principal')),
             f"principal {prop.get('principal')}, secundario {prop.get('secundario')}, estilo {prop.get('estilo')}")

        # ------------------------------------------------ 6. modelo de voz (solo si ya está descargado)
        cache = Path(os.environ.get('HF_HOME', Path.home() / '.cache' / 'huggingface')) / 'hub'
        if cache.exists() and any(cache.glob('models--*faster-whisper-large-v3-turbo*')):
            try:
                from faster_whisper import WhisperModel
                WhisperModel(st.MODELO, device='cpu', compute_type='int8', local_files_only=True)
                paso('El modelo de voz carga', True, st.MODELO)
            except Exception as e:
                paso('El modelo de voz carga', False, str(e)[:120])
        else:
            print('  [ AVISO] Modelo de voz no descargado: no se prueba (se bajará la primera vez, unos 1,6 GB).')

        if conservar:
            cs.SALIDA = ROOT / 'salida'
            cs.SALIDA.mkdir(exist_ok=True)
            copia = cs.nombre_unico('prueba_exportacion')
            shutil.copy(final, copia)
            print(f'\n  Vídeo de prueba guardado en: {copia}')
    except Exception as e:
        paso('La prueba se ha podido completar', False, f'{type(e).__name__}: {str(e)[-600:]}')
    finally:
        fx.cargar_lista = original_cargar_lista
        shutil.rmtree(td, ignore_errors=True)

    print(f'\n(Prueba hecha en {time.time() - t0:.0f} s)')
    if fallos:
        print('RESULTADO: FALLA ' + '; '.join(fallos))
        return 1
    print('RESULTADO: OK')
    return 0


if __name__ == '__main__':
    sys.exit(main(conservar='--conservar' in sys.argv[1:]))

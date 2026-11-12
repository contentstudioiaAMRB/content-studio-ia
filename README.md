# Content Studio IA

Editor de vídeos verticales para creadoras de contenido que funciona en tu ordenador (Windows y Mac):

- **Cortes automáticos** de silencios, que apruebas uno por uno, y paso a vertical 1080×1920.
- **Subtítulos automáticos** con reconocimiento de voz local (tus vídeos no salen de tu ordenador).
- **Efectos**: zoom en los cortes y en las palabras clave, destellos.
- **Pegatinas** (emojis o tus PNG) que aparecen cuando dices ciertas palabras.
- **Tipografías** incluidas: Poppins, Montserrat, Anton, Playfair Display y Dancing Script (licencia OFL).
- **Ficha de marca** por usuaria: colores, letras, tamaño y posición de subtítulos, estilo.
- **Referencias**: analiza capturas y reels que te gustan y propone colores y ritmo.

## Instalar

Abre **Claude Code** en una carpeta cualquiera y pega este mensaje:

```
Instala Content Studio IA siguiendo https://raw.githubusercontent.com/contentstudioiaAMRB/content-studio-ia/main/INSTALAR.md — pídeme permiso antes de instalar programas o descargar archivos grandes, y al final dime si la prueba de exportación salió bien.
```

Claude descarga el programa en `Documentos/Content Studio IA`, comprueba Python y FFmpeg, te pide permiso
para lo que falte, instala las bibliotecas dentro de la carpeta del programa y pasa una prueba de exportación.

También puedes instalarlo a mano: descarga el ZIP (botón **Code → Download ZIP**) y sigue `LEEME-PRIMERO.txt`.

## Requisitos

- Windows 10/11 de 64 bits, o Mac con chip Apple (M1 o posterior) y macOS 14 Sonoma o posterior.
- Unos 3 GB libres e internet durante la instalación.
- Gratuito y se instala aparte: Python 3.12, FFmpeg 7+ y el modelo de voz Whisper large-v3-turbo (1,6 GB).

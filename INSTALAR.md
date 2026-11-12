# Instalar Content Studio IA (instrucciones para Claude Code)

Estas instrucciones son para **Claude**. La usuaria ha pegado un mensaje pidiendo instalar Content Studio IA;
tú haces el trabajo y ella solo contesta cuando le pidas permiso.

## Reglas

- Habla siempre en **español**, con frases cortas y sin tecnicismos. Ella no es programadora.
- **Pide permiso en el chat antes de instalar un programa o descargar algo grande** (Python, FFmpeg,
  el modelo de voz de 1,6 GB). Di qué es, para qué sirve, que es gratuito y cuánto ocupa. Si dice que no,
  respétalo y explica qué no funcionará.
- Las bibliotecas del programa (unos 300 MB) se instalan solo dentro de su carpeta. Avísale de que se
  descargan, pero no hace falta pedir permiso aparte: forman parte de instalar el programa que ha pedido.
- **Nunca** escribas, pidas ni manejes su contraseña. Si algo la necesita (en Mac, Homebrew), ella lo hace
  en la app Terminal y tú le dices exactamente qué pegar.
- No cambies ajustes de seguridad del sistema, no uses `sudo` y no instales nada que no esté en esta guía.
- No subas sus vídeos ni sus datos a ningún sitio. El programa funciona entero en su ordenador.
- Si un paso falla, no improvises otra instalación: enséñale el error en una frase, mira la sección
  «Si algo falla» y, si no se resuelve, dile que se lo pase a quien le compartió el programa.

## Paso 1. Dónde instalar

1. Averigua el sistema: Windows o macOS.
2. La carpeta del programa será **`Content Studio IA`** dentro de la carpeta **Documentos** de la usuaria
   (Windows: `%USERPROFILE%\Documents\Content Studio IA`; Mac: `~/Documents/Content Studio IA`).
   Si su carpeta Documentos está en OneDrive y no existe la ruta normal, usa la que exista.
3. Si esa carpeta **ya existe** y tiene `content_studio.py`, es una actualización: sigue igual (el paso 2
   conserva `marca/`, `entrada/`, `salida/`, `REFERENCIAS/` y `.venv/`). Si existe pero es otra cosa,
   pregúntale qué hacer y no borres nada.

## Paso 2. Descargar el programa

Repositorio: `https://github.com/contentstudioiaAMRB/content-studio-ia` (rama `main`).

- Si `git` está disponible: `git clone https://github.com/contentstudioiaAMRB/content-studio-ia.git "<carpeta>"`
  (si ya existe y es un clon, `git -C "<carpeta>" pull`).
- Si no hay `git`: descarga `https://github.com/contentstudioiaAMRB/content-studio-ia/archive/refs/heads/main.zip`
  en una carpeta temporal **nueva y vacía**, descomprímelo ahí y copia el contenido de
  `content-studio-ia-main/` a la carpeta del programa (sobrescribiendo archivos del programa, nunca
  borrando sus carpetas personales). Windows: `Invoke-WebRequest` + `Expand-Archive`. Mac: `curl -L` + `unzip`.

Comprueba que en la carpeta están `content_studio.py`, `VERSION.txt` e `instalador/`. Dile qué versión
ha bajado (`VERSION.txt`).

## Paso 3. Ver qué falta (sin instalar nada)

Ejecuta el instalador **sin permisos** para que solo compruebe e instale las bibliotecas si ya hay
Python y FFmpeg:

- **Windows** (PowerShell):
  `powershell -NoProfile -ExecutionPolicy Bypass -File "<carpeta>\instalador\instalar.ps1" -NoInteractivo -Prueba`
- **Mac**:
  `bash "<carpeta>/instalador/instalar_mac.sh" --no-interactivo --prueba`

Puede tardar varios minutos (descarga las bibliotecas). Ejecútalo con un tiempo de espera largo
(10 minutos) o en segundo plano. Lee la **última línea `RESULTADO:`** y el código de salida:

| Código | `RESULTADO:` | Qué haces |
|---|---|---|
| 0 | `OK ...` | Ve al paso 5. |
| 10 | `FALTA Python 3.12` | Paso 4: pide permiso para Python. |
| 11 | `FALTA FFmpeg ...` | Paso 4: pide permiso para FFmpeg. |
| 12 | `FALLA la instalación de bibliotecas` | Comprueba internet y repite el paso 3 una vez. |
| 14 / 15 | `FALTA algo` / `FALLA la prueba` | Lee las líneas `FALTA`/`FALLA` y mira «Si algo falla». |
| 16 | `FALLA ruta ... demasiado larga` (Windows) | Pídele permiso para mover la carpeta a `Documentos\Content Studio IA` (o `C:\Content Studio IA`), muévela y repite el paso 3. |
| 20 | `FALTA Homebrew` (Mac) | Paso 4, Mac. |
| 21 / 22 | `NO COMPATIBLE` (Mac) | Explícale el motivo con amabilidad y detente. |

## Paso 4. Pedir permiso e instalar lo que falta

Pregunta **una sola vez** por todo lo que falte, en un mensaje como este (adapta la lista):

> Para que Content Studio IA funcione faltan estas cosas, todas gratuitas:
> - **Python 3.12** (el lenguaje del programa, unos 100 MB)
> - **FFmpeg** (el motor que corta y monta los vídeos, unos 200 MB)
> - **Modelo de voz** para los subtítulos automáticos (1,6 GB, se descarga una vez; si prefieres,
>   se bajará solo la primera vez que pongas subtítulos)
> - (Windows) **Acceso directo** «Content Studio IA» en el Escritorio
>
> ¿Te lo instalo? Puedes decirme sí a todo o solo a algunas.

Después vuelve a ejecutar el instalador **añadiendo solo los permisos que ella haya dado**:

- **Windows**: `-InstalarPython`, `-InstalarFFmpeg`, `-DescargarModelo`, `-AccesoDirecto`
  (usa `winget`, el instalador oficial de Windows; Python se instala solo para su usuario).
  Si Windows muestra una ventana pidiendo permiso, dile que pulse «Sí».
- **Mac**: `--instalar-python`, `--instalar-ffmpeg`, `--descargar-modelo` (usa Homebrew).

Pregunta también por el modelo de voz y el acceso directo aunque no falte nada más.

### Mac sin Homebrew (código 20)

Homebrew pide la contraseña del Mac, así que **lo instala ella**. Dile, paso a paso:

1. Abre la app **Terminal** (Cmd + espacio, escribe «Terminal», Enter).
2. Pega esta línea y pulsa Enter:
   `/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"`
3. Cuando pida **Password**, escribe tu contraseña del Mac (no se ve mientras escribes) y pulsa Enter.
   Si pide pulsar Enter o instalar las «herramientas de línea de comandos», acepta.
4. Cuando termine, avísame.

Luego repite el paso 3 y, si faltan Python o FFmpeg, el paso 4.

## Paso 5. Comprobación final y prueba de exportación

Si la última ejecución no terminó en `RESULTADO: OK (comprobación y prueba de exportación superadas)`,
ejecuta solo la comprobación (no instala nada):

- Windows: `powershell -NoProfile -ExecutionPolicy Bypass -File "<carpeta>\instalador\instalar.ps1" -SoloComprobar -Prueba`
- Mac: `bash "<carpeta>/instalador/instalar_mac.sh" --solo-comprobar --prueba`

Usa **siempre el instalador** para comprobar (no llames a `comprobar.py` directamente): el instalador
pone en el PATH el FFmpeg recién instalado, aunque esta sesión de Claude se abriera antes.

La prueba crea un vídeo sintético (no usa vídeos de nadie), lo corta, lo pasa a vertical, le pone
subtítulos con las tipografías de una marca de ejemplo, zoom, destellos y pegatinas, y comprueba el MP4.
Si quiere ver ese vídeo de prueba: `<python del .venv> instalador/prueba_exportacion.py --conservar`
(queda en `salida/`).

## Paso 6. Explicarle cómo empezar

Con `RESULTADO: OK`, díselo así de claro:

- Está instalado y la prueba de exportación ha salido bien.
- Para abrirlo: **Windows**, el acceso directo «Content Studio IA» del Escritorio (o doble clic en
  «Abrir Content Studio IA» dentro de la carpeta). **Mac**, clic derecho en «Abrir Content Studio IA.command»
  → Abrir (la primera vez).
- La primera vez, opción **1** del menú para configurar su marca (colores, tipografías, estilo).
- Sus vídeos van en la carpeta `entrada`, sus referencias en `REFERENCIAS` y los editados salen en `salida`.
  Sus originales nunca se modifican.
- Si el modelo de voz no se descargó, la primera vez que ponga subtítulos tardará más (1,6 GB).
- Para actualizar en el futuro, basta con volver a pegar el mismo mensaje de instalación.

## Si algo falla

- **Windows, `winget` no existe**: que actualice «Instalador de aplicación» desde Microsoft Store, o que
  instale Python 3.12 desde python.org (marcando «Add python.exe to PATH») y FFmpeg desde gyan.dev.
  Luego repite el paso 3.
- **Acaba de instalarse Python/FFmpeg pero sigue diciendo que falta**: repite el paso 3 una vez; si sigue,
  que cierre Claude del todo, lo vuelva a abrir y pegue de nuevo el mensaje.
- **Mac, `FFmpeg: filtro subtitles` FALTA**: hace falta `ffmpeg-full` (el `ffmpeg` normal de Homebrew no
  trae subtítulos). Pide permiso y ejecuta el instalador con `--instalar-ffmpeg`.
- **`Letra de emojis` FALTA** (raro): las pegatinas de emoji no funcionarán, el resto sí. Las pegatinas en
  PNG (`recursos/pegatinas/<palabra>.png`) siguen funcionando.
- **Sin internet** o descargas cortadas: repite cuando haya conexión; lo hecho no se repite.
- Cualquier otro error: copia las líneas `FALTA`/`FALLA` y dile que se las pase a quien le compartió el programa.

## Requisitos

- Windows 10 u 11 de 64 bits, o Mac con chip Apple (M1 o posterior) y macOS 14 Sonoma o posterior.
- Unos 3 GB libres (programa, bibliotecas y modelo de voz) y conexión a internet para instalar.

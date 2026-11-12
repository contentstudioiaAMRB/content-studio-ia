# Content Studio IA - instalador para Windows (v0.6)
# Comprueba lo que hace falta y, si falta algo, explica qué es y pide permiso antes de instalarlo.
# No cambia ajustes de seguridad de Windows. Todo lo de Python va dentro de la carpeta del programa (.venv).
#
# Dos formas de usarlo:
#  - Con doble clic en «1 - Instalar (Windows).bat»: pregunta en la ventana (s/n).
#  - Desde Claude Code (sin ventana para contestar): -NoInteractivo y los permisos que la usuaria
#    haya dado en el chat: -InstalarPython -InstalarFFmpeg -DescargarModelo -AccesoDirecto.
#    Sin esas opciones no se instala ni se descarga nada grande.
# Al final escribe una línea «RESULTADO: ...» que Claude puede leer.
param(
    [switch]$NoInteractivo,
    [switch]$InstalarPython,
    [switch]$InstalarFFmpeg,
    [switch]$DescargarModelo,
    [switch]$AccesoDirecto,
    [switch]$Prueba,          # al terminar, pasa la prueba de exportación
    [switch]$SoloComprobar,   # no instala nada: solo comprueba (y la prueba si va con -Prueba)
    [switch]$Auto             # compatibilidad con v0.5 = -NoInteractivo
)

$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}
if ($Auto) { $NoInteractivo = $true }
$Raiz = Split-Path -Parent $PSScriptRoot
Set-Location $Raiz
$VenvPy = Join-Path $Raiz '.venv\Scripts\python.exe'
$PyMin = 12   # Python 3.12 o superior (lo exigen numpy y PyAV de requisitos.txt)

function Titulo($t) { Write-Host ''; Write-Host "== $t" -ForegroundColor Cyan }
function Bien($t) { Write-Host "   OK  $t" -ForegroundColor Green }
function Mal($t) { Write-Host "   !!  $t" -ForegroundColor Yellow }
function Resultado($codigo, $texto) {
    Write-Host ''
    Write-Host "RESULTADO: $texto"
    exit $codigo
}
function Permiso($t, [bool]$dado) {
    if ($dado) { Write-Host "$t -> sí (permiso dado)"; return $true }
    if ($NoInteractivo) { Write-Host "$t -> no (sin permiso)"; return $false }
    $r = Read-Host "$t (s/n)"
    return ($r -match '^(s|si|sí|y|yes)$')
}
function RefrescarPath {
    # winget deja Python/FFmpeg en el PATH del sistema; esta ventana se entera aquí
    $m = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $u = [Environment]::GetEnvironmentVariable('Path', 'User')
    $env:Path = "$m;$u"
    # winget instala FFmpeg en una carpeta de paquetes y crea un enlace en Links
    $links = Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Links'
    if ((Test-Path $links) -and ($env:Path -notlike "*$links*")) { $env:Path = "$env:Path;$links" }
}
function HayWinget { return [bool](Get-Command winget -ErrorAction SilentlyContinue) }

function BuscarPython {
    # Devuelve @(comando, argumentos) de un Python 3.12+ real (no el acceso de la Microsoft Store)
    $cands = @()
    if (Get-Command py -ErrorAction SilentlyContinue) {
        foreach ($v in '3.13', '3.12', '3') { $cands += , @('py', @("-$v")) }
    }
    $p = Get-Command python -ErrorAction SilentlyContinue
    if ($p -and $p.Source -notlike '*WindowsApps*') { $cands += , @($p.Source, @()) }
    foreach ($c in $cands) {
        try {
            $v = & $c[0] @($c[1] + @('-c', 'import sys;print(sys.version_info[0],sys.version_info[1],sep=chr(46))')) 2>$null
            if ($v -match '^3\.(\d+)$' -and [int]$Matches[1] -ge $PyMin) { return , $c }
        } catch {}
    }
    return $null
}

function VersionFFmpeg {
    try {
        $l = (& ffmpeg -version 2>$null | Select-Object -First 1)
        if ($l -match 'ffmpeg version n?(\d+)') { return [int]$Matches[1] }
    } catch {}
    return 0
}

function Comprobar {
    if (-not (Test-Path $VenvPy)) { Mal 'Todavía no está instalado (falta la carpeta .venv).'; Resultado 13 'FALTA instalar las bibliotecas (ejecuta el instalador)' }
    & $VenvPy 'instalador\comprobar.py'
    if ($LASTEXITCODE -ne 0) { Resultado 14 'FALTA algo (mira las líneas FALTA de la comprobación)' }
    if ($Prueba) {
        & $VenvPy 'instalador\prueba_exportacion.py'
        if ($LASTEXITCODE -ne 0) { Resultado 15 'FALLA la prueba de exportación' }
    }
    if ($Prueba) { Resultado 0 'OK (comprobación y prueba de exportación superadas)' }
    Resultado 0 'OK (comprobación superada)'
}

Write-Host ''
Write-Host 'CONTENT STUDIO IA 0.6 - INSTALACIÓN EN WINDOWS' -ForegroundColor Magenta
Write-Host "Carpeta del programa: $Raiz"
RefrescarPath

if ($SoloComprobar) { Comprobar }

# ---------------------------------------------------------------- 1. Python
Titulo "1/5  Python 3.$PyMin o superior (el lenguaje en el que está hecho el programa)"
$py = BuscarPython
if ($py) {
    Bien ('Python encontrado: ' + (& $py[0] @($py[1] + @('--version'))))
} else {
    Mal "No he encontrado Python 3.$PyMin o superior."
    if (HayWinget) {
        Write-Host '   Puedo instalar Python 3.12 (gratuito, de python.org) con el instalador oficial de Windows (winget),'
        Write-Host '   solo para tu usuario. Al instalarlo se aceptan las condiciones de Python.'
        if (Permiso '   ¿Instalo Python ahora?' $InstalarPython) {
            winget install -e --id Python.Python.3.12 --scope user --silent --accept-package-agreements --accept-source-agreements
            RefrescarPath
            $py = BuscarPython
        }
    }
    if (-not $py) {
        Mal 'Instala Python 3.12 desde https://www.python.org/downloads/ (marca «Add python.exe to PATH»)'
        Mal 'y vuelve a ejecutar este instalador.'
        Resultado 10 'FALTA Python 3.12 (pide permiso para instalarlo con -InstalarPython)'
    }
    Bien 'Python instalado.'
}

# ---------------------------------------------------------------- 2. FFmpeg
Titulo '2/5  FFmpeg 7 o superior (el motor que corta y monta los vídeos)'
$ffv = VersionFFmpeg
if ($ffv -ge 7) {
    Bien "FFmpeg $ffv encontrado."
} else {
    if ($ffv -gt 0) { Mal "Tienes FFmpeg $ffv; hace falta la 7 o superior." } else { Mal 'No he encontrado FFmpeg.' }
    if (HayWinget) {
        Write-Host '   Puedo instalar FFmpeg (gratuito; versión completa de gyan.dev, la que recomienda ffmpeg.org)'
        Write-Host '   con el instalador oficial de Windows (winget). Al instalarlo se aceptan sus condiciones.'
        if (Permiso '   ¿Instalo FFmpeg ahora?' $InstalarFFmpeg) {
            if ($ffv -gt 0) { winget upgrade -e --id Gyan.FFmpeg --silent --accept-package-agreements --accept-source-agreements }
            else { winget install -e --id Gyan.FFmpeg --silent --accept-package-agreements --accept-source-agreements }
            RefrescarPath
            $ffv = VersionFFmpeg
        }
    }
    if ($ffv -lt 7) {
        Mal 'Instala FFmpeg 7 o superior (https://www.gyan.dev/ffmpeg/builds/) y vuelve a ejecutar este instalador.'
        Resultado 11 'FALTA FFmpeg 7+ (pide permiso para instalarlo con -InstalarFFmpeg)'
    }
    Bien "FFmpeg $ffv listo."
}

# ---------------------------------------------------------------- 3. Bibliotecas
Titulo '3/5  Bibliotecas del programa (reconocimiento de voz y pegatinas, unos 300 MB)'
Write-Host '   Se instalan dentro de la carpeta del programa (.venv), sin tocar el resto del ordenador.'
if (-not (Test-Path $VenvPy)) {
    & $py[0] @($py[1] + @('-m', 'venv', '.venv'))
}
& $VenvPy -m pip install --disable-pip-version-check --quiet -r 'instalador\requisitos.txt'
if ($LASTEXITCODE -ne 0) { Mal 'No se pudieron instalar las bibliotecas. ¿Hay conexión a internet?'; Resultado 12 'FALLA la instalación de bibliotecas (¿internet?)' }
Bien 'Bibliotecas instaladas.'

# ---------------------------------------------------------------- 4. Modelo de voz
Titulo '4/5  Modelo de voz (para los subtítulos)'
Write-Host '   Es un archivo grande (unos 1,6 GB) que se descarga una sola vez de Hugging Face.'
Write-Host '   Si dices que no, se descargará solo la primera vez que pongas subtítulos.'
if (Permiso '   ¿Lo descargo ahora?' $DescargarModelo) {
    & $VenvPy -c "from faster_whisper import WhisperModel; WhisperModel('large-v3-turbo', device='cpu', compute_type='int8'); print('modelo listo')"
    if ($LASTEXITCODE -ne 0) { Mal 'No se pudo descargar el modelo; se intentará la primera vez que pongas subtítulos.' }
}

# ---------------------------------------------------------------- 5. Acceso directo
Titulo '5/5  Acceso directo en el Escritorio'
if (Permiso '   ¿Creo el acceso directo «Content Studio IA» en tu Escritorio?' $AccesoDirecto) {
    $ws = New-Object -ComObject WScript.Shell
    $lnk = $ws.CreateShortcut((Join-Path ([Environment]::GetFolderPath('Desktop')) 'Content Studio IA.lnk'))
    $lnk.TargetPath = Join-Path $Raiz 'Abrir Content Studio IA.bat'
    $lnk.WorkingDirectory = $Raiz
    $lnk.Save()
    Bien 'Acceso directo creado.'
}

Comprobar

# Installs pdfX for the current user: a private Python environment, Ghostscript, and a Start Menu shortcut.
# Safe to run again; it updates an existing install.
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"  # Windows PowerShell 5 downloads are very slow with the progress bar
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12  # GitHub rejects older TLS

$repo = Split-Path -Parent $PSScriptRoot
$dir = Join-Path $env:LOCALAPPDATA "pdfX"
$shortcut = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\pdfX.lnk"

function Step($exe, [string[]]$arguments) {
    & $exe @arguments
    if ($LASTEXITCODE -ne 0) { throw "Command failed: $exe $($arguments -join ' ')" }
}

# 1. Python 3.10 or newer
$python = $null
foreach ($candidate in "py -3", "python") {
    $parts = $candidate -split " "
    try {
        & $parts[0] @($parts | Select-Object -Skip 1) -c "import sys; sys.exit(sys.version_info < (3, 10))" 2>$null
        if ($LASTEXITCODE -eq 0) { $python = $parts; break }
    } catch { }
}
if (-not $python) {
    throw "pdfX needs Python 3.10 or newer. Install it from https://www.python.org/downloads/ (tick 'Add python.exe to PATH'), then run this again."
}

# 2. Virtual environment and pdfX itself
New-Item -ItemType Directory -Force $dir | Out-Null
$venvPython = Join-Path $dir "venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Step $python[0] (@($python | Select-Object -Skip 1) + @("-m", "venv", (Join-Path $dir "venv")))
}
Step $venvPython @("-m", "pip", "install", "--upgrade", $repo)

# 3. Ghostscript (used by Compress), downloaded from Artifex and checked against their published checksum
function Test-Ghostscript {
    foreach ($root in $env:ProgramFiles, ${env:ProgramFiles(x86)}) {
        if ($root -and (Get-ChildItem "$root\gs\gs*\bin\gswin*c.exe" -ErrorAction SilentlyContinue)) { return $true }
    }
    return [bool](Get-Command gswin64c, gswin32c -ErrorAction SilentlyContinue)
}

if (-not (Test-Ghostscript)) {
    Write-Host "Installing Ghostscript (Windows will ask for permission)..."
    try {
        $release = Invoke-RestMethod "https://api.github.com/repos/ArtifexSoftware/ghostpdl-downloads/releases/latest"
        $asset = $release.assets | Where-Object name -match '^gs\d+w64\.exe$' | Select-Object -First 1
        $sums = $release.assets | Where-Object name -eq "SHA512SUMS" | Select-Object -First 1
        $installer = Join-Path $env:TEMP $asset.name
        $sumsFile = Join-Path $env:TEMP "gs-SHA512SUMS"
        Invoke-WebRequest $asset.browser_download_url -OutFile $installer
        Invoke-WebRequest $sums.browser_download_url -OutFile $sumsFile
        $expected = ((Get-Content $sumsFile | Where-Object { $_ -match "\s$($asset.name)$" }) -split "\s+")[0]
        if ((Get-FileHash $installer -Algorithm SHA512).Hash -ne $expected) { throw "checksum mismatch for $($asset.name)" }
        Start-Process $installer -ArgumentList "/S" -Verb RunAs -Wait
        Remove-Item $installer, $sumsFile -ErrorAction SilentlyContinue
    } catch {
        Write-Warning "Could not install Ghostscript automatically ($($_.Exception.Message))."
    }
    if (-not (Test-Ghostscript)) {
        Write-Warning "Compress needs Ghostscript. Install it from https://ghostscript.com/releases/gsdnld.html"
    }
}

# 4. Icon: use src\pdfx\pdfx.ico if the repository has one, otherwise make one from the PNG
$icon = Join-Path $dir "pdfx.ico"
$supplied = Join-Path $repo "src\pdfx\pdfx.ico"
if (Test-Path $supplied) { Copy-Item $supplied $icon -Force } else { Step $venvPython @((Join-Path $PSScriptRoot "make_icon.py"), $icon) }

# 5. Start Menu shortcut to the windowless launcher that pip created from the gui-scripts entry
$target = Join-Path $dir "venv\Scripts\pdfx.exe"
if (-not (Test-Path $target)) { throw "Install finished but $target is missing." }
$link = (New-Object -ComObject WScript.Shell).CreateShortcut($shortcut)
$link.TargetPath = $target
$link.WorkingDirectory = $env:USERPROFILE
$link.IconLocation = $icon
$link.Description = "PDF toolkit"
$link.Save()

Write-Host ""
Write-Host "pdfX is installed. Open the Start menu and search for pdfX."

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "Instale o Python 3 e adicione-o ao PATH do computador usado para compilar o Shadow."
}

$buildEnv = Join-Path $PSScriptRoot ".venv-build-win"
$python = Join-Path $buildEnv "Scripts\python.exe"
python -m venv --clear $buildEnv

if ($LASTEXITCODE -ne 0) { throw "Não foi possível criar o ambiente de compilação." }
& $python -m pip install -r requirements-build.txt
if ($LASTEXITCODE -ne 0) { throw "Não foi possível instalar as dependências de compilação." }

& $python -m unittest discover -p "test_*.py" -v
if ($LASTEXITCODE -ne 0) { throw "Testes falharam; a compilação foi interrompida." }

& $python -m PyInstaller `
    --noconfirm `
    --clean `
    --windowed `
    --onefile `
    --name Shadow `
    --add-data "ui;ui" `
    --collect-data webview `
    --hidden-import webview.platforms.winforms `
    --hidden-import webview.platforms.win32 `
    --hidden-import webview.platforms.edgechromium `
    --collect-all pythonnet `
    --collect-all clr_loader `
    --collect-all psutil `
    --exclude-module webview.platforms.gtk `
    --exclude-module webview.platforms.qt `
    --exclude-module webview.platforms.android `
    --exclude-module webview.platforms.cef `
    --exclude-module webview.platforms.cocoa `
    --exclude-module PyQt5 `
    --exclude-module PyQt6 `
    --exclude-module PySide2 `
    --exclude-module PySide6 `
    --exclude-module gi `
    main.py

if ($LASTEXITCODE -ne 0) {
    throw "A compilação falhou. Veja as mensagens acima."
}

$exePath = Join-Path $PSScriptRoot "dist\Shadow.exe"
$sizeMb = [math]::Round((Get-Item $exePath).Length / 1MB, 1)
Write-Host "Shadow compilado: $exePath ($sizeMb MB)"
Write-Host "O Microsoft Edge WebView2 Runtime é necessário no Windows de destino e não é incluído para manter o pacote menor."

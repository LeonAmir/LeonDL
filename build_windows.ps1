$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Invoke-NativeChecked {
  param(
    [Parameter(Mandatory=$true)][string]$FilePath,
    [Parameter(ValueFromRemainingArguments=$true)][string[]]$Arguments
  )
  & $FilePath @Arguments
  if ($LASTEXITCODE -ne 0) {
    throw "Command failed with exit code $LASTEXITCODE: $FilePath $($Arguments -join ' ')"
  }
}

$version = (Get-Content "VERSION" -Raw).Trim()
$appName = "LeonDL-$version"
$hostName = "LeonDL-Native-Host-$version"

Remove-Item "build" -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item "dist" -Recurse -Force -ErrorAction SilentlyContinue

Invoke-NativeChecked python bootstrap.py --skip-external
Invoke-NativeChecked python later_store_smoke.py
Invoke-NativeChecked python optional_engines_smoke.py
Invoke-NativeChecked python cancel_process_smoke.py
Invoke-NativeChecked python sound_events_smoke.py
Invoke-NativeChecked python sound_ui_smoke.py
Invoke-NativeChecked python browser_bridge_smoke.py
Invoke-NativeChecked python extension_cookie_sync_smoke.py
Invoke-NativeChecked python prerequisite_smoke.py
Invoke-NativeChecked python -m pip install -U pyinstaller

Invoke-NativeChecked python -m PyInstaller `
  --noconfirm `
  --clean `
  --onefile `
  --windowed `
  --name $appName `
  --add-data "assets;assets" `
  --collect-all yt_dlp `
  --collect-all yt_dlp_ejs `
  app.py

Invoke-NativeChecked python -m PyInstaller `
  --noconfirm `
  --clean `
  --onefile `
  --console `
  --name $hostName `
  native_host_entry.py

$releaseDocs = @("README.md", "CHANGELOG.md", "VERSION", "LICENSE")
foreach ($doc in $releaseDocs) {
  if (-not (Test-Path $doc)) { throw "Required release document is missing: $doc" }
  Copy-Item $doc -Destination "dist\$doc" -Force
}

if (-not (Test-Path "chrome_extension\manifest.json")) {
  throw "Chrome extension package is missing."
}
Copy-Item "chrome_extension" -Destination "dist\chrome_extension" -Recurse -Force

if (-not (Test-Path "dist\$appName.exe")) { throw "Main EXE was not created." }
if (-not (Test-Path "dist\$hostName.exe")) { throw "Native Host EXE was not created." }

Write-Host "`nBuild complete: dist\$appName.exe" -ForegroundColor Green
Write-Host "Native host: dist\$hostName.exe" -ForegroundColor Green
Write-Host "Release documentation and Chrome extension copied beside the EXE." -ForegroundColor Green

# Windows PowerShell 5.1; no developer runtime required.
[CmdletBinding()]
param(
    [switch]$Install,
    [string]$DownloadDirectory = (Join-Path $env:TEMP 'codex-usage-prerequisites'),
    [string]$WebView2Installer
)
$ErrorActionPreference = 'Stop'
if (-not [Environment]::Is64BitOperatingSystem -or $env:PROCESSOR_ARCHITECTURE -eq 'ARM64' -or $env:PROCESSOR_ARCHITEW6432 -eq 'ARM64') {
    throw 'This installation guide supports Windows x64 only.'
}
$taskHost = Join-Path $env:LOCALAPPDATA 'Programs/Codex++/codex-plus-plus.exe'
$taskRegistered = Get-ItemProperty 'HKCU:\Software\Codex++' -ErrorAction SilentlyContinue
if ($Install -and ((Test-Path -LiteralPath $taskHost) -or $taskRegistered.InstallDir)) {
    Write-Output 'Codex++ already exists. Preserve it; use the usage installer compatibility check. No downgrade performed.'
    return
}
function Get-WebViewVersion {
    foreach ($taskKey in @(
        'HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}',
        'HKCU:\Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}'
    )) {
        $taskVersion = (Get-ItemProperty $taskKey -ErrorAction SilentlyContinue).pv
        if ($taskVersion -and [version]$taskVersion -gt [version]'0.0.0.0') { return $taskVersion }
    }
}
if ($Install -and -not (Get-WebViewVersion)) {
    if (-not $WebView2Installer) {
        throw 'WebView2 is missing. Download the Evergreen x64 installer from https://developer.microsoft.com/microsoft-edge/webview2/ and rerun with -WebView2Installer <file>.'
    }
    $taskWebView = (Resolve-Path -LiteralPath $WebView2Installer).Path
    $taskSignature = Get-AuthenticodeSignature -LiteralPath $taskWebView
    if ($taskSignature.Status -ne 'Valid' -or $taskSignature.SignerCertificate.Subject -notmatch '(?:^|,\s*)O=Microsoft Corporation(?:,|$)') {
        throw 'WebView2 installer must have a valid Microsoft signature.'
    }
    $taskProcess = Start-Process -FilePath $taskWebView -ArgumentList '/silent','/install' -WindowStyle Hidden -PassThru -Wait
    if ($taskProcess.ExitCode -notin @(0,3010) -or -not (Get-WebViewVersion)) { throw 'WebView2 installation failed or requires a restart.' }
}
$taskName = 'CodexPlusPlus-1.8.0-windows-x64-setup.exe'
$taskSHA = '831d82600370ee7fef600f40fefbc55e3a484e3701a76f8ddcf867ab96962647'
$taskUrl = 'https://github.com/BigPizzaV3/CodexPlusPlus/releases/download/v1.8.0/' + $taskName
New-Item -ItemType Directory -Force -Path $DownloadDirectory | Out-Null
$taskSetup = Join-Path (Resolve-Path -LiteralPath $DownloadDirectory).Path $taskName
if (-not (Test-Path -LiteralPath $taskSetup)) {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -UseBasicParsing -Uri $taskUrl -OutFile $taskSetup
}
if ((Get-FileHash -LiteralPath $taskSetup -Algorithm SHA256).Hash.ToLowerInvariant() -ne $taskSHA) { throw 'Codex++ installer SHA-256 mismatch. Nothing was executed.' }
Write-Output 'Official Codex++ 1.8.0 installer SHA-256 verified.'
if (-not $Install) { Write-Output 'Download only. Rerun with -Install to install for the current user.'; return }
$taskProcess = Start-Process -FilePath $taskSetup -ArgumentList '/S' -WindowStyle Hidden -Wait -PassThru
if ($taskProcess.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $taskHost)) { throw 'Codex++ installation did not finish successfully.' }
$taskHostSHA = (Get-FileHash -LiteralPath $taskHost -Algorithm SHA256).Hash.ToLowerInvariant()
if ($taskHostSHA -ne '48f062f9de96904c4c8169a8ccb0ee978fcca0d33cb1c75df9dee67c453a5d3d') {
    throw 'Installed Codex++ build is not in the reviewed compatibility list. Preserve it and report the hash; do not bypass the usage installer check.'
}
Write-Output 'Codex++ installed. Open Codex++, retain official login, confirm the Codex app path and launch Codex. Then run the usage package Install.cmd and reload scripts.'

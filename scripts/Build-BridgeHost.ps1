param([string]$SourceDirectory = (Join-Path (Split-Path $PSScriptRoot -Parent) '.reference\CodexPlusPlus'))
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path $PSScriptRoot -Parent
$taskSource = [IO.Path]::GetFullPath($SourceDirectory)
$taskInfo = Get-Content (Join-Path $taskRoot 'integration\source.json') -Raw | ConvertFrom-Json
# Local toolchain is optional; CI uses its explicitly installed normal Rust toolchain.
$taskRustHome = Join-Path $taskRoot '.buildtools\rustup'
$taskCargoHome = Join-Path $taskRoot '.buildtools\cargo'
if (Test-Path (Join-Path $taskCargoHome 'bin\cargo.exe')) {
    $env:RUSTUP_HOME = $taskRustHome
    $env:CARGO_HOME = $taskCargoHome
    $env:PATH = (Join-Path $taskCargoHome 'bin') + ';' + $env:PATH
}
$taskRustVersion = & rustc --version
if ($LASTEXITCODE -ne 0 -or $taskRustVersion -notmatch '^rustc 1\.99\.0 ') { throw 'Rust 1.99.0 / MSVC is required.' }
$taskNative = Join-Path $taskRoot '.buildtools\native'
if (Test-Path (Join-Path $taskNative 'native-download.json')) {
    $taskNativeInfo = Get-Content (Join-Path $taskNative 'native-download.json') -Raw | ConvertFrom-Json
    $taskArchive = Join-Path $taskNative 'sherpa-onnx-v1.13.8-win-x64-static-MT-Release-lib.tar.bz2'
    if ((Get-FileHash -LiteralPath $taskArchive -Algorithm SHA256).Hash.ToLowerInvariant() -ne $taskNativeInfo.sha256) {
        throw 'Native dependency cache checksum mismatch.'
    }
    $env:SHERPA_ONNX_ARCHIVE_DIR = $taskNative
}
Push-Location $taskSource
try {
    & node scripts/assemble-renderer-inject.mjs --check
    if ($LASTEXITCODE -ne 0) { throw 'Renderer assembly drift.' }
    Push-Location apps/codex-plus-manager
    try {
        & npm ci
        if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed.' }
        & npm test
        if ($LASTEXITCODE -ne 0) { throw 'Frontend tests failed.' }
        & npm run vite:build
        if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
    } finally { Pop-Location }
    & cargo test --locked --release -p codex-plus-core --lib usage_status::tests
    if ($LASTEXITCODE -ne 0) { throw 'Bridge tests failed.' }
    & cargo test --locked --release -p codex-plus-core --test bridge_routes
    if ($LASTEXITCODE -ne 0) { throw 'Host route tests failed.' }
    & cargo build --locked --release -p codex-plus-manager --bin codex-plus-plus
    if ($LASTEXITCODE -ne 0) { throw 'Bridge build failed.' }
    $taskHost = Join-Path $taskSource 'target\release\codex-plus-plus.exe'
    $taskDist = Join-Path $taskRoot 'dist'
    New-Item -ItemType Directory -Path $taskDist -Force | Out-Null
    @{sourceCommit=$taskInfo.upstreamCommit; bridgeVersion=1; patchSHA256=$taskInfo.patchSHA256;
      sha256=(Get-FileHash -LiteralPath $taskHost -Algorithm SHA256).Hash.ToLowerInvariant();
      testsExecuted=$true; rustVersion=$taskRustVersion; builtAt=[DateTime]::UtcNow.ToString('o')
    } | ConvertTo-Json | Set-Content -Encoding utf8 (Join-Path $taskDist 'bridge-host-build.json')
} finally { Pop-Location }

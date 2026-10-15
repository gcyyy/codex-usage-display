# Runs on Windows PowerShell 5.1. No Python, Node, Git, Rust or extra modules.
[CmdletBinding()]
param(
    [ValidateSet('Smoke','Installed')][string]$Mode = 'Smoke',
    [string]$PackageRoot,
    [string]$InstallDirectory = (Join-Path $env:LOCALAPPDATA 'Programs/CodexUsageStatus'),
    [string]$Output = (Join-Path $env:TEMP 'codex-usage-clean-machine-report.json')
)
$ErrorActionPreference = 'Stop'
$taskReport = [ordered]@{ schemaVersion=1; mode=$Mode; status='running'; os=[Environment]::OSVersion.VersionString; checks=@(); endToEndUI='not-tested'; limitations='PATH isolation is not a clean OS or a second-computer test.' }
$taskOldPath = $env:PATH
$taskOldPythonPath = $env:PYTHONPATH
$taskOldPythonHome = $env:PYTHONHOME
$taskExe = $null
$taskState = $null
$taskStarted = $false
function Assert-Check([bool]$Condition,[string]$Name) {
    if (-not $Condition) { throw ('Check failed: ' + $Name) }
    $taskReport.checks += $Name
}
function Invoke-Collector([string[]]$Arguments) {
    $taskResult = & $taskExe @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) { throw 'Collector command failed (private output omitted).' }
    return ($taskResult -join "`n")
}
try {
    # GitHub Windows runners install py.exe directly in Windows, so exclude
    # the Windows root too. Keep only OS command utilities and PowerShell.
    $env:PATH = "$env:SystemRoot\System32;$env:SystemRoot\System32\WindowsPowerShell\v1.0"
    $env:PYTHONPATH = $null
    $env:PYTHONHOME = $null
    foreach ($taskTool in @('python','python3','py','node','npm','rustc','cargo','git')) {
        Assert-Check (-not (Get-Command $taskTool -ErrorAction SilentlyContinue)) ('not-on-path:' + $taskTool)
    }
    if ($Mode -eq 'Smoke') {
        if (-not $PackageRoot) { throw '-PackageRoot must point to an extracted full release.' }
        $taskPackage = (Resolve-Path -LiteralPath $PackageRoot).Path
        $taskExe = Join-Path $taskPackage 'codex-usage-collector.exe'
        $taskVersion = (Invoke-Collector @('verify-package','--package-root',$taskPackage) | ConvertFrom-Json).version
        $taskReport.version = $taskVersion
        Assert-Check $true 'release-manifest-verified'
        $taskRoot = Join-Path $env:TEMP ('codex-usage-smoke-' + [guid]::NewGuid().ToString('N'))
        $taskTarget = Join-Path $taskRoot 'installed space'
        $taskPlus = Join-Path $taskRoot 'synthetic-plus'
        $taskHostState = Join-Path $taskRoot 'synthetic-host-state'
        $taskHome = Join-Path $taskRoot 'synthetic-home'
        $taskState = Join-Path $taskTarget '.runtime'
        New-Item -ItemType Directory -Force -Path $taskState,(Join-Path $taskHome 'sessions'),$taskPlus,$taskHostState | Out-Null
        $taskEncoding = New-Object Text.UTF8Encoding($false)
        # Entirely synthetic; no real Codex sessions or credentials are read.
        $taskEvents = @'
{"timestamp":"2026-10-13T01:00:00Z","type":"session_meta","payload":{"id":"smoke-session","originator":"Codex Desktop","cli_version":"synthetic-v1","source":"vscode","timestamp":"2026-10-13T01:00:00Z"}}
{"timestamp":"2026-10-14T00:59:00Z","type":"turn_context","payload":{"model":"gpt-6.1-sol","turn_id":"smoke-turn"}}
{"timestamp":"2026-10-14T01:00:00Z","type":"event_msg","payload":{"type":"token_count","info":{"total_token_usage":{"input_tokens":100000,"cached_input_tokens":60000,"cache_write_input_tokens":0,"output_tokens":10000,"reasoning_output_tokens":4000,"total_tokens":110000},"last_token_usage":{"input_tokens":100000,"cached_input_tokens":60000,"cache_write_input_tokens":0,"output_tokens":10000,"reasoning_output_tokens":4000,"total_tokens":110000}}}}
'@
        [IO.File]::WriteAllText((Join-Path $taskHome 'sessions/smoke.jsonl'),$taskEvents+"`n",$taskEncoding)
        Invoke-Collector @('--state',$taskState,'--home',$taskHome,'init') | Out-Null
        $taskConfigFile = Join-Path $taskState 'config.json'
        $taskConfig = Get-Content -LiteralPath $taskConfigFile -Raw | ConvertFrom-Json
        $taskListener = New-Object Net.Sockets.TcpListener([Net.IPAddress]::Loopback,0)
        $taskListener.Start(); $taskConfig.port = $taskListener.LocalEndpoint.Port; $taskListener.Stop()
        [IO.File]::WriteAllText($taskConfigFile,($taskConfig | ConvertTo-Json -Depth 8),$taskEncoding)
        $taskSnapshot = Invoke-Collector @('--state',$taskState,'snapshot','--date','2026-10-14') | ConvertFrom-Json
        Assert-Check ($taskSnapshot.totals.total -eq 110000) 'synthetic-token-total-110000'
        Assert-Check ([decimal]$taskSnapshot.totalCostUSD -eq [decimal]'0.186') 'synthetic-cost-0.186'
        # No host settings: installation must fail without creating the installed EXE.
        $taskOptions = @('install','--package-root',$taskPackage,'--install-dir',$taskTarget,'--codex-plus-dir',$taskPlus,'--host-state',$taskHostState)
        $taskSavedPreference = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        & $taskExe @taskOptions *> $null
        $taskMissingExit = $LASTEXITCODE
        $ErrorActionPreference = $taskSavedPreference
        Assert-Check ($taskMissingExit -ne 0 -and -not (Test-Path (Join-Path $taskTarget 'codex-usage-collector.exe'))) 'missing-codex-plus-refused'
        [IO.File]::WriteAllText((Join-Path $taskPlus 'user_scripts.json'),'{"enabled":false,"scripts":{"user:other.js":false},"unrelated":42}',$taskEncoding)
        [IO.File]::WriteAllText((Join-Path $taskHostState 'usage-status.json'),'{}',$taskEncoding)
        $taskBeforeConfig = (Get-FileHash -LiteralPath $taskConfigFile).Hash
        $taskStarted = $true
        Invoke-Collector $taskOptions | Out-Null
        Invoke-Collector $taskOptions | Out-Null
        Assert-Check ((Get-FileHash -LiteralPath $taskConfigFile).Hash -eq $taskBeforeConfig) 'install-repeat-preserves-config'
        Invoke-Collector @('--state',$taskState,'diagnose') | Out-Null
        Assert-Check $true 'installed-service-healthy'
        $taskScript = Get-Content (Join-Path $taskPlus 'user_scripts/codex-usage-status.js') -Raw
        Assert-Check (-not $taskScript.Contains($taskConfig.pairingToken)) 'renderer-has-no-pairing-token'
        $taskUninstall = Join-Path $taskTarget 'scripts/Uninstall.ps1'
        & "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File $taskUninstall -InstallDirectory $taskTarget | Out-Null
        Assert-Check ($LASTEXITCODE -eq 0 -and -not (Test-Path (Join-Path $taskTarget 'codex-usage-collector.exe'))) 'shipped-uninstaller'
        $taskAfter = Get-Content (Join-Path $taskPlus 'user_scripts.json') -Raw | ConvertFrom-Json
        Assert-Check ($taskAfter.unrelated -eq 42 -and $taskAfter.scripts.'user:other.js' -eq $false -and -not $taskAfter.enabled) 'unrelated-settings-preserved'
        Assert-Check (Test-Path -LiteralPath $taskConfigFile) 'data-retained'
        $taskStarted = $false
        $taskReport.hostInstallation = 'synthetic-settings-only; real Codex++ replacement NOT tested'
    } else {
        $taskExe = Join-Path $InstallDirectory 'codex-usage-collector.exe'
        $taskState = Join-Path $InstallDirectory '.runtime'
        $taskReceipt = Get-Content (Join-Path $InstallDirectory 'installation.json') -Raw | ConvertFrom-Json
        $taskReport.version = $taskReceipt.version
        $taskHealth = Invoke-Collector @('--state',$taskState,'diagnose') | ConvertFrom-Json
        Assert-Check ($taskHealth.status -eq 'ok') 'installed-service-healthy'
        $taskScript = Get-Content -LiteralPath $taskReceipt.scriptPath -Raw
        Assert-Check ($taskScript -match '"transport"\s*:\s*"bridge"') 'bridge-script-installed'
        $taskSettings = Get-Content -LiteralPath $taskReceipt.settingsPath -Raw | ConvertFrom-Json
        Assert-Check ($taskSettings.enabled -and $taskSettings.scripts.'user:codex-usage-status.js') 'script-enabled'
        Assert-Check ((Get-FileHash -LiteralPath $taskReceipt.hostPath).Hash.ToLowerInvariant() -eq $taskReceipt.hostSHA256) 'installed-host-hash'
        $taskReport.indexStatus = $taskHealth.indexStatus
        $taskReport.hostInstallation = 'installed-files-checked; manual UI acceptance still required'
    }
    $taskReport.status = 'passed'
} catch {
    $taskReport.status = 'failed'
    $taskReport.error = 'A check failed; inspect the local console. No credentials included in this report.'
    throw
} finally {
    if ($Mode -eq 'Smoke' -and $taskStarted -and $taskExe -and $taskState) {
        & $taskExe --state $taskState stop *> $null
    }
    $env:PATH = $taskOldPath; $env:PYTHONPATH = $taskOldPythonPath; $env:PYTHONHOME = $taskOldPythonHome
    $taskOutputPath = [IO.Path]::GetFullPath($Output)
    [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($taskOutputPath)) | Out-Null
    $taskReport | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $taskOutputPath -Encoding UTF8
    Write-Output ('Report: ' + $taskOutputPath)
}
$taskReport | ConvertTo-Json -Depth 8

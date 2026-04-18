param(
    [string]$BackendUrl = "http://localhost:5000",
    [string]$DashboardUrl = "http://localhost:3000/dashboard",
    [string]$BackendLogPath = "",
    [string]$SensorLogPath = "",
    [string]$DashboardLogPath = ""
)

function Write-Step {
    param(
        [string]$Number,
        [string]$Title
    )

    Write-Host ""
    Write-Host "[$Number] $Title" -ForegroundColor Cyan
}

function Test-Endpoint {
    param(
        [string]$Name,
        [string]$Url
    )

    try {
        $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 10
        Write-Host ("  [OK] {0} -> {1}" -f $Name, $response.StatusCode) -ForegroundColor Green
        return $true
    }
    catch {
        Write-Host ("  [FAIL] {0} -> {1}" -f $Name, $_.Exception.Message) -ForegroundColor Red
        return $false
    }
}

function Test-LogMarker {
    param(
        [string]$Name,
        [string]$Path,
        [string[]]$Patterns
    )

    if ([string]::IsNullOrWhiteSpace($Path)) {
        Write-Host ("  [SKIP] {0} log path not provided" -f $Name) -ForegroundColor Yellow
        return
    }

    if (-not (Test-Path -LiteralPath $Path)) {
        Write-Host ("  [FAIL] {0} log path not found: {1}" -f $Name, $Path) -ForegroundColor Red
        return
    }

    foreach ($pattern in $Patterns) {
        $match = Select-String -Path $Path -Pattern $pattern -SimpleMatch -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($null -ne $match) {
            Write-Host ("  [OK] {0} contains {1}" -f $Name, $pattern) -ForegroundColor Green
        }
        else {
            Write-Host ("  [WAIT] {0} missing {1}" -f $Name, $pattern) -ForegroundColor Yellow
        }
    }
}

Write-Host "ZeinaGuard Realtime Pipeline Validation" -ForegroundColor White
Write-Host ("Backend URL  : {0}" -f $BackendUrl)
Write-Host ("Dashboard URL: {0}" -f $DashboardUrl)

Write-Step "1" "Backend and dashboard reachability"
$backendHealthy = Test-Endpoint -Name "Backend /health" -Url "$BackendUrl/health"
$networksHealthy = Test-Endpoint -Name "Dashboard bootstrap /api/dashboard/networks" -Url "$BackendUrl/api/dashboard/networks?limit=5"
$threatsHealthy = Test-Endpoint -Name "Dashboard bootstrap /api/dashboard/threat-events" -Url "$BackendUrl/api/dashboard/threat-events?limit=5"
$sensorHealthy = Test-Endpoint -Name "Dashboard bootstrap /api/dashboard/sensor-health" -Url "$BackendUrl/api/dashboard/sensor-health"
Write-Host "  Open the dashboard in a browser and keep it visible:"
Write-Host ("  {0}" -f $DashboardUrl)

Write-Step "2" "Start the sensor"
Write-Host "  Use your normal sensor startup command, for example:"
Write-Host "  python .\sensor\main.py"
Write-Host "  Expected startup checkpoints:"
Write-Host "  - virtual environment bootstraps if missing"
Write-Host "  - requirements install if needed"
Write-Host "  - interface selection prompt appears"
Write-Host "  - sensor registers with backend"

Write-Step "3" "Validate scan flow"
Write-Host "  Confirm a live network appears on the dashboard within a few seconds."
Write-Host "  Expected log markers:"
Write-Host "  - Sensor   : [QUEUE] queued network_scan"
Write-Host "  - Sensor   : [SEND] event=network_scan"
Write-Host "  - Backend  : [RECEIVED FROM SENSOR] event=network_scan"
Write-Host "  - Backend  : [EMIT TO DASHBOARD] event=network_scan"
Write-Host "  - Dashboard: [EVENT RECEIVED] network_scan"

Write-Step "4" "Trigger a manual attack"
Write-Host "  Click Attack for a live network row in the dashboard."
Write-Host "  The dashboard must send:"
Write-Host "  { sensor_id, target_bssid, channel, action: 'deauth' }"
Write-Host "  Expected log markers:"
Write-Host "  - Dashboard: [SOCKET EMIT] attack_command"
Write-Host "  - Backend  : [FORWARD COMMAND] event=attack_command"
Write-Host "  - Sensor   : [COMMAND RECEIVED] attack_command"

Write-Step "5" "Validate attack acknowledgment"
Write-Host "  Expected feedback loop:"
Write-Host "  - Sensor executes only if sensor_id matches"
Write-Host "  - Sensor sends attack_ack"
Write-Host "  - Backend forwards attack_ack"
Write-Host "  - Dashboard shows success or failure notification"
Write-Host "  Expected log markers:"
Write-Host "  - Sensor   : [ATTACK EXECUTED]"
Write-Host "  - Sensor   : [QUEUE] queued attack_ack"
Write-Host "  - Backend  : [RECEIVED FROM SENSOR] event=attack_ack"
Write-Host "  - Backend  : [EMIT TO DASHBOARD] event=attack_ack"
Write-Host "  - Dashboard: [EVENT RECEIVED] attack_ack"

Write-Step "6" "Validate live sensor status"
Write-Host "  Wait at least 5 seconds and confirm the dashboard sensor card updates."
Write-Host "  Expected metrics:"
Write-Host "  - cpu"
Write-Host "  - memory"
Write-Host "  - uptime"
Write-Host "  Expected log markers:"
Write-Host "  - Sensor   : [QUEUE] queued sensor_status"
Write-Host "  - Sensor   : [SEND] event=sensor_status"
Write-Host "  - Backend  : [RECEIVED FROM SENSOR] event=sensor_status"
Write-Host "  - Backend  : [EMIT TO DASHBOARD] event=sensor_status"
Write-Host "  - Dashboard: [EVENT RECEIVED] sensor_status"

Write-Step "7" "Optional log scan"
Test-LogMarker -Name "Backend" -Path $BackendLogPath -Patterns @(
    "[RECEIVED FROM SENSOR]",
    "[EMIT TO DASHBOARD]",
    "[FORWARD COMMAND]"
)
Test-LogMarker -Name "Sensor" -Path $SensorLogPath -Patterns @(
    "[QUEUE]",
    "[SEND]",
    "[COMMAND RECEIVED]",
    "[ATTACK EXECUTED]"
)
Test-LogMarker -Name "Dashboard" -Path $DashboardLogPath -Patterns @(
    "[SOCKET CONNECTED]",
    "[EVENT RECEIVED]",
    "[SOCKET EMIT] attack_command"
)

Write-Step "Result" "Manual pass criteria"
$reachabilityPassed = $backendHealthy -and $networksHealthy -and $threatsHealthy -and $sensorHealthy
if ($reachabilityPassed) {
    Write-Host "  Backend bootstrap endpoints are reachable." -ForegroundColor Green
} else {
    Write-Host "  Fix backend reachability before validating the realtime flow." -ForegroundColor Red
}
Write-Host "  Final pass requires:"
Write-Host "  - networks render live without UI freezing"
Write-Host "  - attack is forwarded only to the selected sensor_id"
Write-Host "  - attack_ack is shown on the dashboard"
Write-Host "  - sensor_status updates every ~5 seconds with real cpu/memory/uptime"

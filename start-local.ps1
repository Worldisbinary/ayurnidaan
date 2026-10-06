# Start Ayurnidaan locally: API (port 8000) + app (port 8081), each in its own window.
# Usage (PowerShell, from anywhere):   E:\projects\ayur-analytics\start-local.ps1
# Stop: close the two windows.

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$node = "E:\tools\node"

# Free the ports if an old instance is still running
foreach ($port in 8000, 8081) {
    Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
        ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
}

# Bring the local database schema up to date (safe to run every time)
& "$root\.venv\Scripts\alembic.exe" -c "$root\alembic.ini" upgrade head

$api = "Set-Location '$root'; `$env:AYUR_ENVIRONMENT='development'; " +
       "`$env:AYUR_BOOTSTRAP_ADMIN_EMAIL='admin@demo.ayurnidaan.in'; `$env:PYTHONIOENCODING='utf-8'; " +
       "& '.venv\Scripts\python.exe' -m uvicorn ayurnidaan.app.main:app --port 8000"
Start-Process powershell -ArgumentList "-NoExit", "-Command", $api -WindowStyle Normal

$web = "Set-Location '$root\mobile'; `$env:Path='$node;' + `$env:Path; " +
       "`$env:EXPO_PUBLIC_API_URL='http://localhost:8000'; `$env:BROWSER='none'; " +
       "& '$node\npx.cmd' expo start --web --port 8081"
Start-Process powershell -ArgumentList "-NoExit", "-Command", $web -WindowStyle Normal

function Test-Port([int]$port) {
    $client = New-Object System.Net.Sockets.TcpClient
    try { $client.Connect("127.0.0.1", $port); return $true } catch { return $false } finally { $client.Close() }
}

Write-Host "Waiting for the app to start..."
for ($i = 0; $i -lt 60; $i++) {  # up to ~2 minutes
    if ((Test-Port 8000) -and (Test-Port 8081)) { break }
    Start-Sleep -Seconds 2
}
Start-Sleep -Seconds 3  # let the app finish its first build
Start-Process "http://localhost:8081"
Write-Host "Ayurnidaan is running: app http://localhost:8081  |  API docs http://localhost:8000/docs"

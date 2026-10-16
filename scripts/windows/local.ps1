<#
.SYNOPSIS
  One-click start / stop for a single local user on Windows.

.DESCRIPTION
  start      Start Postgres (if not already listening), run migrations, start the
             backend (7860) and the Vite dev server (5173), then open the browser.
  stop       Stop the frontend, backend and Postgres.
  status     Show what is listening.
  shortcuts  Put "RPG Roleplay" and "Stop RPG Roleplay" shortcuts on the desktop.

  Usually run through start-local.cmd / stop-local.cmd in the repo root.

  Postgres: if 127.0.0.1:5432 is already listening it is used as-is. Otherwise the
  script looks for a portable Postgres in $env:RPG_PG_DIR (default: a sibling
  folder named rpg-pg next to the repo) containing start-pg.cmd / stop-pg.cmd, or
  pg\bin\pg_ctl.exe + data\. A Postgres installed as a Windows service just needs
  to be running.

  Auth is off in local mode (RPG_REQUIRE_AUTH unset), so there is no login step.
#>
param(
    [Parameter(Position = 0)]
    [ValidateSet('start', 'stop', 'status', 'shortcuts')]
    [string]$Action = 'start',
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'

$Repo        = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$RpgDir      = Join-Path $Repo 'rpg'
$FrontendDir = Join-Path $Repo 'frontend'
$LogDir      = Join-Path $Repo '.dev-logs'
$PidFile     = Join-Path $LogDir 'local-pids.json'
$PgDir       = if ($env:RPG_PG_DIR) { $env:RPG_PG_DIR } else { Join-Path (Split-Path $Repo -Parent) 'rpg-pg' }
$Python      = Join-Path $RpgDir '.venv\Scripts\python.exe'

$PgPort       = 5432
$BackendPort  = 7860
$FrontendPort = 5173
$AppUrl       = "http://localhost:$FrontendPort/"

function Say([string]$msg, [string]$color = 'Gray') { Write-Host $msg -ForegroundColor $color }

function Get-PortOwner([int]$port) {
    $c = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($c) { return [int]$c.OwningProcess }
    return $null
}

function Test-Port([int]$port) { return $null -ne (Get-PortOwner $port) }

function Wait-Port([int]$port, [int]$seconds, [string]$name) {
    $deadline = (Get-Date).AddSeconds($seconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-Port $port) { return }
        Start-Sleep -Milliseconds 500
    }
    throw "$name did not start listening on port $port within $seconds s (see $LogDir)."
}

function Stop-Tree([int]$procId) {
    # taskkill /T takes the whole child tree (npm -> cmd -> node, venv launcher -> python).
    & taskkill.exe /PID $procId /T /F 2>&1 | Out-Null
}

function Read-DotEnv([string]$path) {
    $vars = @{}
    if (-not (Test-Path $path)) { return $vars }
    foreach ($line in Get-Content $path -Encoding UTF8) {
        if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$') {
            $v = $Matches[2]
            if ($v -match '^"(.*)"$' -or $v -match "^'(.*)'$") { $v = $Matches[1] }
            $vars[$Matches[1]] = $v
        }
    }
    return $vars
}

# Run a program with stdout/stderr going to log files and set $LASTEXITCODE. Not using
# PowerShell's own redirection: on 5.1 it turns native stderr into terminating errors.
function Invoke-Logged([string]$log, [string]$exe, [string[]]$argv) {
    $p = Start-Process -FilePath $exe -ArgumentList $argv -NoNewWindow -Wait -PassThru `
        -RedirectStandardOutput $log -RedirectStandardError "$log.err"
    $global:LASTEXITCODE = $p.ExitCode
}

function Get-FilesHash([string[]]$paths) {
    ($paths | Where-Object { Test-Path $_ } | ForEach-Object { (Get-FileHash $_ -Algorithm SHA256).Hash }) -join ','
}

# Re-install dependencies only when their manifest changed since the last install
# (e.g. after a git pull added a package), tracked by a hash stamp file.
function Sync-Deps([string]$name, [string[]]$manifests, [string]$stamp, [scriptblock]$install, [string]$log) {
    if ((Test-Path $stamp) -and ((Get-Content $stamp -Raw).Trim() -eq (Get-FilesHash $manifests))) { return }
    Say "${name}: installing dependencies (first run or they changed)"
    & $install $log
    if ($LASTEXITCODE -ne 0) { throw "$name dependency install failed (see $log)." }
    Set-Content -Encoding ASCII $stamp (Get-FilesHash $manifests)
}

function Start-Postgres {
    if (Test-Port $PgPort) { Say "Postgres: already running on $PgPort"; return }
    $startCmd = Join-Path $PgDir 'start-pg.cmd'
    $pgCtl    = Join-Path $PgDir 'pg\bin\pg_ctl.exe'
    # Launched detached rather than piped: postgres.exe inherits pg_ctl's handles, so
    # piping its output would block here for as long as Postgres runs.
    if (Test-Path $startCmd) {
        Say "Postgres: starting ($startCmd)"
        Start-Process -FilePath 'cmd.exe' -ArgumentList '/d', '/c', "`"$startCmd`"" -WindowStyle Hidden
    } elseif (Test-Path $pgCtl) {
        Say "Postgres: starting ($pgCtl)"
        Start-Process -FilePath $pgCtl -WindowStyle Hidden -ArgumentList `
            '-D', "`"$(Join-Path $PgDir 'data')`"", '-l', "`"$(Join-Path $PgDir 'postgres.log')`"", `
            '-o', "`"-p $PgPort -c listen_addresses=127.0.0.1`"", 'start'
    } else {
        throw "Postgres is not running on port $PgPort and no portable install was found in '$PgDir'. Start it yourself or set RPG_PG_DIR."
    }
    Wait-Port $PgPort 30 'Postgres'
}

function Stop-Postgres {
    if (-not (Test-Port $PgPort)) { Say 'Postgres: not running'; return }
    $stopCmd = Join-Path $PgDir 'stop-pg.cmd'
    $pgCtl   = Join-Path $PgDir 'pg\bin\pg_ctl.exe'
    if (Test-Path $stopCmd) {
        & cmd.exe /c "`"$stopCmd`"" | Out-Null
    } elseif (Test-Path $pgCtl) {
        & $pgCtl -D (Join-Path $PgDir 'data') stop -m fast | Out-Null
    } else {
        Say "Postgres: running, but not from '$PgDir'; leaving it alone" 'Yellow'
        return
    }
    Say 'Postgres: stopped'
}

function Invoke-Start {
    if (-not (Test-Path $Python)) { throw "Backend venv not found at $Python. Create it first (see README)." }
    New-Item -ItemType Directory -Force $LogDir | Out-Null
    $pids = @{}

    Start-Postgres

    # migrate doesn't read rpg\.env itself, so hand it DATABASE_URL (and anything else in .env).
    $envVars = Read-DotEnv (Join-Path $RpgDir '.env')
    foreach ($k in $envVars.Keys) { Set-Item -Path "Env:$k" -Value $envVars[$k] }
    if (-not $env:DATABASE_URL) { throw "DATABASE_URL is not set in rpg\.env." }

    Say 'Database: applying migrations'
    Push-Location $RpgDir
    try {
        Invoke-Logged (Join-Path $LogDir 'migrate.log') $Python @('-m', 'platform_app.migrate', 'full')
        if ($LASTEXITCODE -ne 0) { throw "Migrations failed (see $LogDir\migrate.log)." }
    } finally { Pop-Location }

    if (Test-Port $BackendPort) {
        Say "Backend: already running on $BackendPort"
    } else {
        $req = Join-Path $RpgDir 'requirements.txt'
        Sync-Deps 'Backend' @($req) (Join-Path $RpgDir '.venv\.rpg-local-deps') `
            { param($log) Invoke-Logged $log $Python @('-m', 'pip', 'install', '-r', "`"$req`"") } (Join-Path $LogDir 'pip-install.log')
        Say "Backend: starting on $BackendPort"
        $p = Start-Process -FilePath $Python -WorkingDirectory $RpgDir -WindowStyle Hidden -PassThru `
            -ArgumentList '-m', 'uvicorn', 'app:app', '--host', '127.0.0.1', '--port', "$BackendPort" `
            -RedirectStandardOutput (Join-Path $LogDir 'backend.out.log') `
            -RedirectStandardError  (Join-Path $LogDir 'backend.log')
        $pids.backend = $p.Id
    }

    if (Test-Port $FrontendPort) {
        Say "Frontend: already running on $FrontendPort"
    } else {
        Push-Location $FrontendDir
        try {
            Sync-Deps 'Frontend' @((Join-Path $FrontendDir 'package.json'), (Join-Path $FrontendDir 'package-lock.json')) `
                (Join-Path $FrontendDir 'node_modules\.rpg-local-deps') { param($log) Invoke-Logged $log 'cmd.exe' @('/d', '/c', 'npm install') } (Join-Path $LogDir 'npm-install.log')
        } finally { Pop-Location }
        Say "Frontend: starting on $FrontendPort"
        $p = Start-Process -FilePath 'cmd.exe' -WorkingDirectory $FrontendDir -WindowStyle Hidden -PassThru `
            -ArgumentList '/d', '/c', 'npm run dev' `
            -RedirectStandardOutput (Join-Path $LogDir 'frontend.log') `
            -RedirectStandardError  (Join-Path $LogDir 'frontend.err.log')
        $pids.frontend = $p.Id
    }

    if ($pids.Count) { $pids | ConvertTo-Json | Set-Content -Encoding UTF8 $PidFile }

    Wait-Port $BackendPort 120 'Backend'
    Wait-Port $FrontendPort 60 'Frontend'

    Say "Ready: $AppUrl" 'Green'
    if (-not $NoBrowser) { Start-Process $AppUrl }
}

function Invoke-Stop {
    if (Test-Path $PidFile) {
        $saved = Get-Content $PidFile -Raw | ConvertFrom-Json
        foreach ($name in 'frontend', 'backend') {
            if ($saved.$name -and (Get-Process -Id $saved.$name -ErrorAction SilentlyContinue)) {
                Stop-Tree $saved.$name
            }
        }
        Remove-Item $PidFile -Force
    }
    # Whatever still holds the ports (e.g. started by hand) goes too.
    foreach ($entry in @(@('Frontend', $FrontendPort), @('Backend', $BackendPort))) {
        $owner = Get-PortOwner $entry[1]
        if ($owner) { Stop-Tree $owner }
        Say "$($entry[0]): stopped"
    }
    Stop-Postgres
}

function Invoke-Status {
    foreach ($entry in @(@('Postgres', $PgPort), @('Backend', $BackendPort), @('Frontend', $FrontendPort))) {
        $state = if (Test-Port $entry[1]) { 'running' } else { 'stopped' }
        Say ("{0,-9} {1,-5} {2}" -f $entry[0], $entry[1], $state)
    }
}

function Invoke-Shortcuts {
    $desktop = [Environment]::GetFolderPath('Desktop')
    $shell = New-Object -ComObject WScript.Shell
    foreach ($s in @(
            @{ Name = 'RPG Roleplay';      Target = 'start-local.cmd'; Icon = 'imageres.dll,1023'; Desc = 'Start RPG Roleplay and open it in the browser' },
            @{ Name = 'Stop RPG Roleplay'; Target = 'stop-local.cmd';  Icon = 'imageres.dll,1027'; Desc = 'Stop RPG Roleplay (frontend, backend, Postgres)' })) {
        $lnk = $shell.CreateShortcut((Join-Path $desktop "$($s.Name).lnk"))
        $lnk.TargetPath       = Join-Path $Repo $s.Target
        $lnk.WorkingDirectory = $Repo
        $lnk.IconLocation     = "$env:SystemRoot\System32\$($s.Icon)"
        $lnk.Description      = $s.Desc
        $lnk.WindowStyle      = 7  # minimized
        $lnk.Save()
        Say "Shortcut: $($s.Name)"
    }
}

switch ($Action) {
    'start'     { Invoke-Start }
    'stop'      { Invoke-Stop }
    'status'    { Invoke-Status }
    'shortcuts' { Invoke-Shortcuts }
}

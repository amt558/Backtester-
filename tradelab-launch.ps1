# tradelab -- environment launcher (v2)
#
# Double-click tradelab-launch.bat (same folder) to run this.
#
# What it does:
#   - runs tradelab doctor at startup (blocks only on critical fails)
#   - starts optuna-dashboard in the background (if not already on :8080)
#   - rebuilds reports/index.html
#   - opens index + optuna-dashboard in default browser
#   - interactive menu: pick strategy / universe / action
#   - one-press "compare last 2 runs of active strategy"
#   - "recent runs" picker to jump straight into any recent dashboard
#   - kill optuna-dashboard cleanly (option k)
#   - install a Desktop shortcut to this launcher (option i)
#
# Data source: Twelve Data (no AmiBroker/CSV dependency).

$ErrorActionPreference = "Stop"

# --- paths -----------------------------------------------------------
$TradelabRoot = "C:\TradingScripts\tradelab"
$VenvScripts  = "C:\TradingScripts\.venv-vectorbt\Scripts"
$Tradelab     = Join-Path $VenvScripts "tradelab.exe"
$VenvPython   = Join-Path $VenvScripts "python.exe"
$Optuna       = Join-Path $VenvScripts "optuna-dashboard.exe"
$RunCanaries  = Join-Path $TradelabRoot "scripts\run_canaries.py"
$OptunaStore  = "sqlite:///C:/TradingScripts/tradelab/.cache/optuna_studies.db"
$IndexHtml    = Join-Path $TradelabRoot "reports\index.html"
$DashboardUrl = "http://127.0.0.1:8080"

# --- UTF-8 so Rich + plotext render correctly ------------------------
$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
try { [Console]::InputEncoding = [System.Text.Encoding]::UTF8 } catch {}

# --- preflight -------------------------------------------------------
function Fail($msg) {
    Write-Host "[error] $msg" -ForegroundColor Red
    Read-Host "press enter to close"
    exit 1
}
foreach ($p in @($Tradelab, $VenvPython, $Optuna)) {
    if (-not (Test-Path $p)) { Fail "not found: $p" }
}
Set-Location $TradelabRoot

# --- helpers ---------------------------------------------------------

function Test-Port8080 {
    try {
        $t = [System.Net.Sockets.TcpClient]::new()
        $a = $t.BeginConnect("127.0.0.1", 8080, $null, $null)
        $ok = $a.AsyncWaitHandle.WaitOne(300, $false)
        if ($ok) { $t.EndConnect($a); $t.Close(); return $true }
        $t.Close(); return $false
    } catch { return $false }
}

function Start-OptunaDashboard {
    if (Test-Port8080) {
        Write-Host "[ok]    optuna-dashboard already on :8080" -ForegroundColor Green
        return
    }
    Write-Host "[start] launching optuna-dashboard in background..." -ForegroundColor Yellow
    Start-Process -FilePath $Optuna -ArgumentList "`"$OptunaStore`"" -WindowStyle Minimized
    for ($i = 0; $i -lt 10; $i++) {
        Start-Sleep -Milliseconds 500
        if (Test-Port8080) {
            Write-Host "[ok]    optuna-dashboard up on :8080" -ForegroundColor Green
            return
        }
    }
    Write-Host "[warn]  optuna-dashboard didn't confirm within 5s" -ForegroundColor Yellow
}

function Stop-OptunaDashboard {
    $killed = $false
    try {
        $conns = Get-NetTCPConnection -LocalPort 8080 -State Listen -ErrorAction SilentlyContinue
        foreach ($c in $conns) {
            try {
                Stop-Process -Id $c.OwningProcess -Force -ErrorAction Stop
                $killed = $true
            } catch {}
        }
    } catch {}
    if (-not $killed) {
        Get-Process -Name optuna-dashboard -ErrorAction SilentlyContinue |
            ForEach-Object { $_ | Stop-Process -Force; $killed = $true }
    }
    if ($killed) {
        Write-Host "[ok]    optuna-dashboard stopped" -ForegroundColor Green
    } else {
        Write-Host "[info]  no optuna-dashboard process found" -ForegroundColor Yellow
    }
}

function Invoke-DoctorStartupCheck {
    Write-Host "[step]  running tradelab doctor..." -ForegroundColor Yellow
    $output = & $Tradelab doctor 2>&1 | Out-String
    $critical = $output -match "Doctor: 1\+ critical checks failed"
    if ($critical) {
        Write-Host $output
        Write-Host "[fail]  doctor flagged critical failure -- fix before continuing" -ForegroundColor Red
        $ans = Read-Host "continue anyway? (y/N)"
        if ($ans -notmatch '^[yY]') { exit 1 }
    } else {
        # extract just the pass count for a compact startup banner
        $fails = [regex]::Matches($output, "FAIL\s+(\S+)")
        if ($fails.Count -gt 0) {
            Write-Host "[warn]  doctor: $($fails.Count) non-critical fail(s):" -ForegroundColor Yellow
            foreach ($m in $fails) { Write-Host "          - $($m.Groups[1].Value)" -ForegroundColor Yellow }
        } else {
            Write-Host "[ok]    doctor: all checks passed" -ForegroundColor Green
        }
    }
}

function Get-TradelabMeta {
    $script = @"
import json
from tradelab import __version__
from tradelab.config import get_config
from tradelab.determinism import git_commit_hash
cfg = get_config()
out = {
  'strategies': [
    {'name': n, 'status': e.status, 'description': e.description}
    for n, e in cfg.strategies.items()
  ],
  'universes': sorted(cfg.universes.keys()),
  'universes_full': {n: list(v) for n, v in cfg.universes.items()},
  'data_start': cfg.defaults.data_start,
  'version': __version__,
  'git_commit': (git_commit_hash() or 'unknown'),
  'config_path': str(cfg.config_path),
}
print(json.dumps(out))
"@
    $json = & $VenvPython -c $script 2>$null
    if ($LASTEXITCODE -eq 0 -and $json) { return ($json | ConvertFrom-Json) }
    return $null
}

function Test-CommandCenterRunning {
    try {
        $t = [System.Net.Sockets.TcpClient]::new()
        $a = $t.BeginConnect("127.0.0.1", 8877, $null, $null)
        $ok = $a.AsyncWaitHandle.WaitOne(300, $false)
        if ($ok) { $t.EndConnect($a); $t.Close(); return $true }
        $t.Close(); return $false
    } catch { return $false }
}

function Invoke-AlgoTradeCenter {
    $url = "http://localhost:8877/command_center.html"
    if (Test-CommandCenterRunning) {
        Write-Host "[ok]   AlgoTrade Command Center already running - opening URL" -ForegroundColor Green
        Start-Process $url
        return
    }
    $bat = "C:\TradingScripts\Launch_Dashboard.bat"
    if (-not (Test-Path $bat)) {
        Write-Host "[fail] Launch_Dashboard.bat not found at $bat" -ForegroundColor Red
        return
    }
    Write-Host "[start] launching AlgoTrade Command Center in a new window..." -ForegroundColor Yellow
    # New cmd window so the server runs independently; browser auto-opens from
    # the Python script itself. Launcher stays usable.
    Start-Process -FilePath cmd.exe -ArgumentList "/c", "`"$bat`"" -WorkingDirectory "C:\TradingScripts"
    # Wait briefly for the server to bind, then open the URL ourselves
    # in case the python auto-open didn't fire.
    for ($i = 0; $i -lt 10; $i++) {
        Start-Sleep -Milliseconds 500
        if (Test-CommandCenterRunning) { break }
    }
    Write-Host "[ok]   command center started (http://localhost:8877)" -ForegroundColor Green
}

function Save-YamlBackup {
    $yaml = Join-Path $TradelabRoot "tradelab.yaml"
    if (-not (Test-Path $yaml)) { return $null }
    $dir = Join-Path $TradelabRoot ".cache\yaml_backups"
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $target = Join-Path $dir "tradelab_$stamp.yaml"
    Copy-Item $yaml $target -Force
    # Rotate: keep last 10
    $all = Get-ChildItem $dir -Filter "tradelab_*.yaml" | Sort-Object LastWriteTime -Descending
    if ($all.Count -gt 10) {
        $all | Select-Object -Skip 10 | Remove-Item -Force -ErrorAction SilentlyContinue
    }
    return $target
}

function Restore-YamlFromLatestBackup {
    $dir = Join-Path $TradelabRoot ".cache\yaml_backups"
    if (-not (Test-Path $dir)) { return $false }
    $latest = Get-ChildItem $dir -Filter "tradelab_*.yaml" |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $latest) { return $false }
    $yaml = Join-Path $TradelabRoot "tradelab.yaml"
    Copy-Item $latest.FullName $yaml -Force
    Write-Host "[ok]   yaml restored from backup: $($latest.Name)" -ForegroundColor Green
    return $true
}

function Open-InEditor {
    param([string]$path)
    $vscode = Get-Command code -ErrorAction SilentlyContinue
    if ($vscode) {
        Write-Host "[edit] opening in VS Code (--wait blocks until you close the tab)" -ForegroundColor DarkGray
        & code --wait $path
    } else {
        Write-Host "[edit] opening in Notepad (close window when done)" -ForegroundColor DarkGray
        Start-Process -FilePath notepad.exe -ArgumentList "`"$path`"" -Wait
    }
}

function Test-StrategyLoads {
    param([string]$name)
    $script = @"
import sys
from tradelab.registry import load_strategy_class
try:
    cls = load_strategy_class('$name')
    print(f'OK: {cls.__name__}')
except Exception as e:
    print(f'FAIL: {type(e).__name__}: {e}')
    sys.exit(1)
"@
    $out = & $VenvPython -c $script 2>&1 | Out-String
    return @{ success = ($LASTEXITCODE -eq 0); message = $out.Trim() }
}

# Runtime smoke test -- exercises generate_signals + run_backtest end-to-end on
# smoke_5 (5 mega-caps, sub-second). Catches bugs that slip past an import
# check (NameError inside entry_signal, KeyError on an unknown column, etc).
function Test-StrategyRuns {
    param([string]$name)
    $script = @"
import sys, traceback
try:
    from tradelab.data import load_universe
    from tradelab.marketdata.enrich import enrich_universe
    from tradelab.engines.backtest import run_backtest
    from tradelab.registry import instantiate_strategy

    strat = instantiate_strategy('$name')
    data = load_universe(['SPY', 'NVDA', 'MSFT', 'AAPL', 'META'], benchmark='SPY')
    data = enrich_universe(data, benchmark='SPY')
    spy_close = data['SPY'].set_index('Date')['Close']
    res = run_backtest(strat, data, spy_close=spy_close)
    print(f'OK: {res.metrics.total_trades} trades, PF {res.metrics.profit_factor:.2f}')
except Exception as e:
    print(f'RUNTIME_FAIL: {type(e).__name__}: {e}')
    # Emit the last few frames so the user can see what line blew up
    tb = traceback.format_exc().splitlines()
    for line in tb[-6:]:
        print(line)
    sys.exit(1)
"@
    $out = & $VenvPython -c $script 2>&1 | Out-String
    return @{ success = ($LASTEXITCODE -eq 0); message = $out.Trim() }
}

function Register-StrategyInYaml {
    param([string]$name, [string]$className)
    $module = "tradelab.strategies.$name"
    $script = @"
import sys
import yaml
from pathlib import Path

p = Path('tradelab.yaml')
data = yaml.safe_load(p.read_text(encoding='utf-8'))
if 'strategies' not in data or data['strategies'] is None:
    data['strategies'] = {}
if '$name' in data['strategies']:
    print('ALREADY_REGISTERED')
    sys.exit(2)
data['strategies']['$name'] = {
    'module': '$module',
    'class_name': '$className',
    'description': 'User-added strategy (via ns)',
    'status': 'registered',
    'params': {},
}
p.write_text(yaml.safe_dump(data, sort_keys=False, default_flow_style=False), encoding='utf-8')
print('REGISTERED')
"@
    $out = & $VenvPython -c $script 2>&1 | Out-String
    return @{ exit_code = $LASTEXITCODE; output = $out.Trim() }
}

function Get-StrategySourcePath {
    param([string]$name)
    $script = @"
import importlib.util, sys
from tradelab.config import get_config
try:
    cfg = get_config()
    entry = cfg.strategies.get('$name')
    if entry is None:
        sys.exit(1)
    spec = importlib.util.find_spec(entry.module)
    print(spec.origin if spec and spec.origin else '')
except Exception:
    sys.exit(1)
"@
    $path = (& $VenvPython -c $script 2>$null | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $path) { return $null }
    return $path
}

function Get-DataFreshness {
    # Returns age (hours) of newest parquet file in .cache/ohlcv/1D/ --
    # the cache `tradelab run` consumes via download_symbols.
    # No CSV fallback: tradelab is Twelve-Data / parquet only.
    $script = @"
import json
from pathlib import Path
from datetime import datetime
from tradelab.config import get_config
try:
    cfg = get_config()
    cache_root = Path(cfg.paths.cache_dir) / 'ohlcv' / '1D'
    if not cache_root.exists():
        print('null'); raise SystemExit
    files = list(cache_root.glob('*.parquet'))
    if not files:
        print('null'); raise SystemExit
    newest = max(files, key=lambda p: p.stat().st_mtime)
    age_h = (datetime.now().timestamp() - newest.stat().st_mtime) / 3600.0
    print(json.dumps({
        'age_hours': round(age_h, 1),
        'newest': newest.name,
        'n_files': len(files),
    }))
except Exception:
    print('null')
"@
    $json = (& $VenvPython -c $script 2>$null | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $json -or $json -eq 'null') { return $null }
    try { return ($json | ConvertFrom-Json) } catch { return $null }
}

function Invoke-DataRefresh {
    param([string]$universe)
    $today = (Get-Date -Format 'yyyy-MM-dd')
    Write-Host "[refresh] pulling Twelve Data for universe '$universe' through $today..." -ForegroundColor Yellow
    $script = @"
import sys, time
from tradelab.config import get_config
from tradelab.marketdata import download_symbols

cfg = get_config()
if '$universe' not in cfg.universes:
    print(f'UNIVERSE_NOT_FOUND: $universe')
    sys.exit(1)

symbols = list(cfg.universes['$universe'])
start_dt = cfg.defaults.data_start
end_dt = '$today'

t0 = time.time()
try:
    data = download_symbols(symbols, start=start_dt, end=end_dt)
    elapsed = time.time() - t0
    print(f'OK: refreshed {len(data)} of {len(symbols)} symbols in {elapsed:.1f}s')
except Exception as e:
    print(f'FAIL: {type(e).__name__}: {e}')
    sys.exit(1)
"@
    $out = & $VenvPython -c $script 2>&1 | Out-String
    if ($LASTEXITCODE -eq 0) {
        Write-Host "[ok]   $($out.Trim())" -ForegroundColor Green
        return $true
    }
    Write-Host "[fail] $($out.Trim())" -ForegroundColor Red
    return $false
}

function Get-LatestRunInfo {
    param([string]$strategy)
    $script = @"
import json
from datetime import datetime, timezone
from pathlib import Path
from tradelab.audit.history import list_runs
rows = list_runs(strategy='$strategy', limit=1)
if not rows:
    print('null'); raise SystemExit
r = rows[0]
age_days = None
try:
    ts = datetime.fromisoformat((r.timestamp_utc or '').replace('Z', '+00:00'))
    age_days = round((datetime.now(timezone.utc) - ts).total_seconds() / 86400, 2)
except Exception:
    pass
folder = ''
if r.report_card_html_path:
    try:
        folder = str(Path(r.report_card_html_path).parent).replace('\\', '/')
    except Exception:
        pass
print(json.dumps({
    'verdict': (r.verdict or 'UNKNOWN').upper(),
    'age_days': age_days,
    'folder': folder,
}))
"@
    $json = (& $VenvPython -c $script 2>$null | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $json -or $json -eq 'null') { return $null }
    try { return ($json | ConvertFrom-Json) } catch { return $null }
}

function Invoke-OpenTearsheet {
    param([string]$strategy, [string]$prefer = "richest")
    $info = Get-LatestRunInfo -strategy $strategy
    if (-not $info -or -not $info.folder) {
        Write-Host "[none]  no runs found for '$strategy' - do a run first" -ForegroundColor Yellow
        return
    }
    if ($info.age_days -ne $null -and $info.age_days -gt 1.0) {
        Write-Host ("[stale] latest run is {0:N1} days old - consider a fresh run" -f $info.age_days) -ForegroundColor Yellow
    }
    $target = $null
    if ($prefer -eq "quantstats") {
        $cand = Join-Path $info.folder "quantstats_tearsheet.html"
        if (Test-Path $cand) { $target = $cand }
    } else {
        foreach ($fname in @("robustness_tearsheet.html", "dashboard.html", "quantstats_tearsheet.html")) {
            $cand = Join-Path $info.folder $fname
            if (Test-Path $cand) { $target = $cand; break }
        }
    }
    if (-not $target) {
        Write-Host "[fail] no tearsheet file found in $($info.folder)" -ForegroundColor Red
        return
    }
    Write-Host "[open] $target" -ForegroundColor Cyan
    Start-Process $target
}

$StrategyScaffoldTemplate = @'
"""__NAME__ -- TODO one-line description.

Entry rules:
  - TODO: describe entry conditions

Stop: tradelab default (Close - stop_atr_mult * ATR)
Exit: tradelab default (trailing ATR + SMA50 break)
Score: RS_21d for slot ranking (override if you want different)
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from .simple import SimpleStrategy


class __CLASS__(SimpleStrategy):
    name = "__NAME__"
    timeframe = "1D"
    requires_benchmark = True

    default_params = {
        # --- strategy-specific params (add yours below) ---
        # 'atr_pct_max': 8.0,
        # 'rs_threshold': 0.0,

        # --- engine exit params (leave these unless you know why) ---
        'stop_atr_mult': 1.5,
        'trail_tight_mult': 1.0,
        'trail_wide_mult': 2.0,
        'trail_tighten_atr': 1.5,
    }

    tunable_params = {
        # param_name: (low, high)  --  for Optuna search space
        'stop_atr_mult': (1.0, 2.5),
    }

    def entry_signal(
        self,
        row: pd.Series,
        prev: Optional[pd.Series],
        params: dict,
        prev2: Optional[pd.Series] = None,
    ) -> bool:
        """Return True to enter a long on this bar.

        Enriched columns available on `row`:
          Open, High, Low, Close, Volume, ATR, ATR_pct,
          SMA10/21/50/200, EMA10/21, Vol_MA20, Vol_Ratio,
          Trend_OK, Above50, Pocket_Pivot, RS_21d
        """
        if prev is None:
            return False
        # TODO: implement your entry logic. Return True on entry bars.
        return False

    def entry_score(
        self,
        row: pd.Series,
        prev: Optional[pd.Series],
        params: dict,
        prev2: Optional[pd.Series] = None,
    ) -> float:
        """Higher score wins when slots are tight. Default: use RS_21d."""
        return float(row.get("RS_21d", 1.0) or 0.0)
'@

function Invoke-NewStrategy {
    Write-Host ""
    $name = (Read-Host "  strategy name (snake_case, e.g. my_breakout_v1)").Trim()
    if (-not $name -or $name -notmatch '^[a-z][a-z0-9_]*$') {
        Write-Host "[fail] invalid name - use snake_case starting with a lowercase letter" -ForegroundColor Red
        return
    }
    $className = (Read-Host "  class name (PascalCase, e.g. MyBreakoutV1)").Trim()
    if (-not $className -or $className -notmatch '^[A-Z][A-Za-z0-9_]*$') {
        Write-Host "[fail] invalid class name - use PascalCase" -ForegroundColor Red
        return
    }

    $filePath = Join-Path $TradelabRoot "src\tradelab\strategies\$name.py"
    if (Test-Path $filePath) {
        $ans = (Read-Host "  file exists: $filePath -- overwrite? (y/N)").Trim().ToLower()
        if ($ans -ne 'y') { Write-Host "[skip] cancelled." -ForegroundColor Yellow; return }
    }

    # Write scaffold (save under the user's preferred editor for paste/edit)
    $content = $StrategyScaffoldTemplate -replace '__NAME__', $name -replace '__CLASS__', $className
    $content | Set-Content -Path $filePath -Encoding UTF8
    Write-Host "[step] scaffold written: $filePath" -ForegroundColor Yellow

    Open-InEditor $filePath

    $backup = Save-YamlBackup
    $reg = Register-StrategyInYaml -name $name -className $className
    if ($reg.exit_code -ne 0) {
        if ($reg.output -match 'ALREADY_REGISTERED') {
            Write-Host "[info] '$name' was already in yaml - skipping yaml write" -ForegroundColor DarkGray
        } else {
            Write-Host "[fail] yaml registration failed:" -ForegroundColor Red
            Write-Host $reg.output -ForegroundColor DarkYellow
            return
        }
    } else {
        Write-Host "[ok]   registered '$name' in tradelab.yaml (backup: $($backup | Split-Path -Leaf))" -ForegroundColor Green
    }

    # Stage 1: import validation
    $test = Test-StrategyLoads -name $name
    if (-not $test.success) {
        Write-Host "[fail] '$name' does not import cleanly - rolling back yaml" -ForegroundColor Red
        Write-Host $test.message -ForegroundColor DarkYellow
        Restore-YamlFromLatestBackup | Out-Null
        Write-Host "[info] source file LEFT in place: $filePath (fix it, then re-run ns)" -ForegroundColor DarkGray
        return
    }
    Write-Host "[ok]   '$name' imports cleanly" -ForegroundColor Green

    # Stage 2: runtime smoke test on smoke_5 (2-3s). Catches bugs the
    # import check can't see -- the strategy must actually RUN to be real.
    Write-Host "[step] runtime smoke test on smoke_5..." -ForegroundColor DarkGray
    $runtime = Test-StrategyRuns -name $name
    if (-not $runtime.success) {
        Write-Host "[fail] '$name' imports but crashes at runtime:" -ForegroundColor Red
        Write-Host $runtime.message -ForegroundColor DarkYellow
        $ans = (Read-Host "  keep registered anyway so you can fix and retry? (y/N)").Trim().ToLower()
        if ($ans -ne 'y') {
            Restore-YamlFromLatestBackup | Out-Null
            Write-Host "[info] yaml rolled back. Source kept: $filePath" -ForegroundColor DarkGray
            return
        }
        Write-Host "[warn] strategy left registered but BROKEN - fix before running" -ForegroundColor Yellow
    } else {
        Write-Host "[ok]   runtime: $($runtime.message -replace '^OK:\s*', '')" -ForegroundColor Green
    }
    $script:activeStrategy = $name
    Save-LauncherState $activeStrategy $activeUniverse
    Write-Host "[ok]   active strategy -> $name" -ForegroundColor Green
}

function Invoke-DeleteStrategy {
    $target = (Read-Host "  delete which strategy? (blank = active: $activeStrategy)").Trim()
    if (-not $target) { $target = $activeStrategy }

    # Refuse to delete canaries - they're tool-health anchors
    $canaries = @("rand_canary", "overfit_canary", "leak_canary", "survivor_canary")
    if ($canaries -contains $target) {
        Write-Host "[refuse] '$target' is a canary - never delete these (tool-health)" -ForegroundColor Red
        return
    }

    # Count audit rows referencing this strategy
    $script = @"
import json
from tradelab.audit.history import list_runs
rows = list_runs(strategy='$target', limit=10000)
print(json.dumps({'n_runs': len(rows)}))
"@
    $audit = (& $VenvPython -c $script 2>$null | Out-String).Trim()
    $nRuns = 0
    if ($audit) { try { $nRuns = ($audit | ConvertFrom-Json).n_runs } catch {} }

    $src = Get-StrategySourcePath -name $target
    $srcInfo = if ($src) { $src } else { "(not on disk)" }

    Write-Host ""
    Write-Host "  about to delete: $target" -ForegroundColor Yellow
    Write-Host "    source:     $srcInfo" -ForegroundColor DarkGray
    Write-Host "    audit rows: $nRuns" -ForegroundColor DarkGray
    $ans = (Read-Host "  proceed? (y/N)").Trim().ToLower()
    if ($ans -ne 'y') { Write-Host "[skip] cancelled." -ForegroundColor Yellow; return }

    # Backup yaml and remove entry
    $backup = Save-YamlBackup
    $script2 = @"
import sys, yaml
from pathlib import Path
p = Path('tradelab.yaml')
data = yaml.safe_load(p.read_text(encoding='utf-8'))
if '$target' not in (data.get('strategies') or {}):
    print('NOT_FOUND'); sys.exit(1)
del data['strategies']['$target']
p.write_text(yaml.safe_dump(data, sort_keys=False, default_flow_style=False), encoding='utf-8')
print('REMOVED')
"@
    $out = & $VenvPython -c $script2 2>&1 | Out-String
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[fail] yaml removal failed: $out" -ForegroundColor Red
        return
    }
    Write-Host "[ok]   removed '$target' from yaml (backup: $($backup | Split-Path -Leaf))" -ForegroundColor Green

    # Archive the source file rather than deleting
    if ($src -and (Test-Path $src)) {
        $archiveDir = Join-Path $TradelabRoot "src\tradelab\strategies\_archive"
        if (-not (Test-Path $archiveDir)) { New-Item -ItemType Directory -Path $archiveDir -Force | Out-Null }
        $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
        $archiveName = "${target}_${stamp}.py"
        $archivePath = Join-Path $archiveDir $archiveName
        Move-Item $src $archivePath -Force
        Write-Host "[ok]   source archived: src/tradelab/strategies/_archive/$archiveName" -ForegroundColor Green
    }

    # Offer to clean audit rows for this strategy
    if ($nRuns -gt 0) {
        $ans2 = (Read-Host "  also delete $nRuns audit row(s) for '$target'? (y/N)").Trim().ToLower()
        if ($ans2 -eq 'y') {
            $script3 = @"
import sqlite3
from pathlib import Path
db = Path('data') / 'tradelab_history.db'
if db.exists():
    conn = sqlite3.connect(str(db))
    n = conn.execute("DELETE FROM runs WHERE strategy_name = ?", ('$target',)).rowcount
    conn.commit(); conn.close()
    print(f'Deleted {n} rows')
"@
            $out3 = & $VenvPython -c $script3 2>&1 | Out-String
            Write-Host "[ok]   $($out3.Trim())" -ForegroundColor Green
        }
    }

    # Reset active if we deleted it
    if ($target -eq $activeStrategy) {
        $script:activeStrategy = "s2_pocket_pivot"
        Save-LauncherState $activeStrategy $activeUniverse
        Write-Host "[ok]   active strategy reset -> s2_pocket_pivot" -ForegroundColor Green
    }

    & $Tradelab rebuild-index --no-open | Out-Null
    & $Tradelab overview --no-open | Out-Null
}

function Invoke-CloneStrategy {
    $src = (Read-Host "  clone which strategy? (blank = active: $activeStrategy)").Trim()
    if (-not $src) { $src = $activeStrategy }

    $newName = (Read-Host "  new name (snake_case)").Trim()
    if (-not $newName -or $newName -notmatch '^[a-z][a-z0-9_]*$') {
        Write-Host "[fail] invalid name - use snake_case" -ForegroundColor Red; return
    }
    $newClass = (Read-Host "  new class name (PascalCase)").Trim()
    if (-not $newClass -or $newClass -notmatch '^[A-Z][A-Za-z0-9_]*$') {
        Write-Host "[fail] invalid class name - use PascalCase starting with capital" -ForegroundColor Red; return
    }

    $srcPath = Get-StrategySourcePath -name $src
    if (-not $srcPath -or -not (Test-Path $srcPath)) {
        Write-Host "[fail] cannot find source for '$src' (external module or missing)" -ForegroundColor Red; return
    }

    $newPath = Join-Path $TradelabRoot "src\tradelab\strategies\$newName.py"
    if (Test-Path $newPath) {
        Write-Host "[fail] file already exists: $newPath" -ForegroundColor Red; return
    }

    # Resolve source class name + params from yaml for faithful clone
    $script = @"
import sys, yaml, json
from pathlib import Path
data = yaml.safe_load(Path('tradelab.yaml').read_text(encoding='utf-8'))
entry = (data.get('strategies') or {}).get('$src')
if entry is None:
    print('NO_SRC'); sys.exit(1)
out = {'class_name': entry.get('class_name'), 'params': entry.get('params') or {}}
print(json.dumps(out))
"@
    $srcMeta = (& $VenvPython -c $script 2>$null | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $srcMeta) {
        Write-Host "[fail] could not read source yaml entry" -ForegroundColor Red; return
    }
    $srcMetaObj = $srcMeta | ConvertFrom-Json
    $srcClass = $srcMetaObj.class_name

    # Copy source, rename class + change `name =` attribute
    $content = Get-Content $srcPath -Raw
    $content = $content -replace "class\s+$srcClass\b", "class $newClass"
    $content = $content -replace ('(?m)^(\s*name\s*=\s*)"[^"]*"', "`$1`"$newName`"")
    $content | Set-Content -Path $newPath -Encoding UTF8
    Write-Host "[ok]   copied source to: $newPath" -ForegroundColor Green

    # Register in yaml WITH the source's params
    $backup = Save-YamlBackup
    $paramsJson = ($srcMetaObj.params | ConvertTo-Json -Compress)
    if (-not $paramsJson -or $paramsJson -eq 'null') { $paramsJson = '{}' }
    $script2 = @"
import sys, yaml, json
from pathlib import Path
p = Path('tradelab.yaml')
data = yaml.safe_load(p.read_text(encoding='utf-8'))
if 'strategies' not in data or data['strategies'] is None:
    data['strategies'] = {}
if '$newName' in data['strategies']:
    print('ALREADY_REGISTERED'); sys.exit(2)
data['strategies']['$newName'] = {
    'module': 'tradelab.strategies.$newName',
    'class_name': '$newClass',
    'description': 'Cloned from $src (via nc)',
    'status': 'registered',
    'params': json.loads('''$paramsJson'''),
}
p.write_text(yaml.safe_dump(data, sort_keys=False, default_flow_style=False), encoding='utf-8')
print('REGISTERED')
"@
    $regOut = & $VenvPython -c $script2 2>&1 | Out-String
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[fail] registration failed: $regOut" -ForegroundColor Red
        Remove-Item $newPath -Force -ErrorAction SilentlyContinue
        return
    }

    # Two-stage validation (import + runtime)
    $test = Test-StrategyLoads -name $newName
    if (-not $test.success) {
        Write-Host "[fail] clone fails import:" -ForegroundColor Red
        Write-Host $test.message -ForegroundColor DarkYellow
        Restore-YamlFromLatestBackup | Out-Null
        Remove-Item $newPath -Force -ErrorAction SilentlyContinue
        return
    }
    $runtime = Test-StrategyRuns -name $newName
    if (-not $runtime.success) {
        Write-Host "[warn] clone imports but fails runtime:" -ForegroundColor Red
        Write-Host $runtime.message -ForegroundColor DarkYellow
        $ans = (Read-Host "  keep anyway? (y/N)").Trim().ToLower()
        if ($ans -ne 'y') {
            Restore-YamlFromLatestBackup | Out-Null
            Remove-Item $newPath -Force -ErrorAction SilentlyContinue
            return
        }
    } else {
        Write-Host "[ok]   runtime: $($runtime.message -replace '^OK:\s*', '')" -ForegroundColor Green
    }

    $script:activeStrategy = $newName
    Save-LauncherState $activeStrategy $activeUniverse
    Write-Host "[ok]   cloned $src -> $newName (params carried over, class: $newClass)" -ForegroundColor Green
    Write-Host "[ok]   active strategy -> $newName" -ForegroundColor Green
}

function Invoke-EditActive {
    $path = Get-StrategySourcePath -name $activeStrategy
    if (-not $path -or -not (Test-Path $path)) {
        Write-Host "[fail] cannot resolve source file for '$activeStrategy' (external module?)" -ForegroundColor Red
        return
    }
    Write-Host "[step] editing $path (save & close to validate)..." -ForegroundColor Yellow
    Open-InEditor $path

    # Stage 1: import validation
    $test = Test-StrategyLoads -name $activeStrategy
    if (-not $test.success) {
        Write-Host "[warn] your edit broke the import:" -ForegroundColor Red
        Write-Host $test.message -ForegroundColor DarkYellow
        Write-Host "[info] fix and re-run 'ne' - nothing was registered with yaml" -ForegroundColor DarkGray
        return
    }
    Write-Host "[ok]   '$activeStrategy' still imports cleanly" -ForegroundColor Green

    # Stage 2: runtime smoke test. Warn-only; don't touch yaml.
    Write-Host "[step] runtime smoke test on smoke_5..." -ForegroundColor DarkGray
    $runtime = Test-StrategyRuns -name $activeStrategy
    if (-not $runtime.success) {
        Write-Host "[warn] imports OK, but crashes at runtime:" -ForegroundColor Red
        Write-Host $runtime.message -ForegroundColor DarkYellow
        Write-Host "[info] fix and re-run 'ne'" -ForegroundColor DarkGray
    } else {
        Write-Host "[ok]   runtime: $($runtime.message -replace '^OK:\s*', '')" -ForegroundColor Green
    }
}

function Invoke-PromoteParams {
    # Pull the most recent run's params (what the strategy actually ran with,
    # which for --optimize/--full runs is the Optuna-best set) and offer to
    # make them the yaml defaults.
    $script = @"
import json
from pathlib import Path
from tradelab.audit.history import list_runs
from tradelab.results import BacktestResult
from tradelab.config import get_config

rows = list_runs(strategy='$activeStrategy', limit=1)
if not rows:
    print(json.dumps({'error': 'no runs for this strategy'}))
    raise SystemExit
r = rows[0]
if not r.report_card_html_path:
    print(json.dumps({'error': 'run has no folder reference'}))
    raise SystemExit
folder = Path(r.report_card_html_path).parent
jf = folder / 'backtest_result.json'
if not jf.exists():
    print(json.dumps({'error': 'run predates JSON persistence'}))
    raise SystemExit
bt = BacktestResult.model_validate_json(jf.read_text(encoding='utf-8'))
run_params = dict(bt.params)

cfg = get_config()
entry = cfg.strategies.get('$activeStrategy')
yaml_params = dict((entry.params or {})) if entry else {}

diff = {}
for k, v in run_params.items():
    if yaml_params.get(k) != v:
        diff[k] = {'yaml': yaml_params.get(k), 'run': v}

print(json.dumps({
    'run_id': r.run_id[:8],
    'run_timestamp': r.timestamp_utc,
    'verdict': r.verdict,
    'diff': diff,
    'run_params': run_params,
}))
"@
    $json = (& $VenvPython -c $script 2>$null | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $json) {
        Write-Host "[fail] could not read run params" -ForegroundColor Red; return
    }
    $info = $json | ConvertFrom-Json
    if ($info.error) {
        Write-Host "[skip] $($info.error)" -ForegroundColor Yellow; return
    }

    if (-not $info.diff -or $info.diff.PSObject.Properties.Count -eq 0) {
        Write-Host "[info] latest run used params identical to yaml defaults - nothing to promote." -ForegroundColor DarkGray
        return
    }

    Write-Host ""
    Write-Host "  latest run: $($info.run_id) ($($info.run_timestamp))  verdict: $($info.verdict)" -ForegroundColor Cyan
    Write-Host "  param diff (yaml -> run):" -ForegroundColor Cyan
    foreach ($prop in $info.diff.PSObject.Properties) {
        $k = $prop.Name
        $yaml = $prop.Value.yaml
        $run = $prop.Value.run
        $yamlStr = if ($null -eq $yaml) { "(unset)" } else { [string]$yaml }
        $runStr = [string]$run
        Write-Host ("    {0,-25}  {1,-12}  ->  {2}" -f $k, $yamlStr, $runStr)
    }
    Write-Host ""
    Write-Host "[note] FRAGILE verdicts should rarely be promoted - those params failed the gauntlet." -ForegroundColor DarkGray
    $ans = (Read-Host "  promote these params to yaml defaults? (y/N)").Trim().ToLower()
    if ($ans -ne 'y') { Write-Host "[skip] cancelled." -ForegroundColor Yellow; return }

    # Backup + apply
    $backup = Save-YamlBackup
    $runParamsJson = ($info.run_params | ConvertTo-Json -Compress)
    $script2 = @"
import sys, yaml, json
from pathlib import Path
p = Path('tradelab.yaml')
data = yaml.safe_load(p.read_text(encoding='utf-8'))
strat = (data.get('strategies') or {}).get('$activeStrategy')
if strat is None:
    print('NOT_FOUND'); sys.exit(1)
new_params = json.loads('''$runParamsJson''')
strat['params'] = new_params
p.write_text(yaml.safe_dump(data, sort_keys=False, default_flow_style=False), encoding='utf-8')
print('PROMOTED')
"@
    $out = & $VenvPython -c $script2 2>&1 | Out-String
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[fail] yaml write failed: $out" -ForegroundColor Red
        return
    }

    # Validate strategy still loads and runs
    $test = Test-StrategyLoads -name $activeStrategy
    if (-not $test.success) {
        Write-Host "[fail] promoted params break strategy import - rolling back yaml" -ForegroundColor Red
        Restore-YamlFromLatestBackup | Out-Null
        return
    }
    $runtime = Test-StrategyRuns -name $activeStrategy
    if (-not $runtime.success) {
        Write-Host "[fail] promoted params cause runtime failure - rolling back yaml" -ForegroundColor Red
        Write-Host $runtime.message -ForegroundColor DarkYellow
        Restore-YamlFromLatestBackup | Out-Null
        return
    }
    Write-Host "[ok]   params promoted to '$activeStrategy' yaml defaults (backup: $($backup | Split-Path -Leaf))" -ForegroundColor Green
    Write-Host "[ok]   runtime check: $($runtime.message -replace '^OK:\s*', '')" -ForegroundColor Green
}

function Show-HelpGlossary {
    Write-Host ""
    Write-Host "================================================================" -ForegroundColor Cyan
    Write-Host "  tradelab launcher -- key glossary" -ForegroundColor Cyan
    Write-Host "================================================================" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  HOME (quick views)" -ForegroundColor Yellow
    Write-Host "    t    Open latest tearsheet for active strategy. Prefers the richest:"
    Write-Host "         robustness_tearsheet > dashboard > quantstats. Warns if >24h old."
    Write-Host "    ts   Open quantstats tearsheet specifically - compact, trader-format summary."
    Write-Host "    o    Build + open portfolio overview: one row per registered strategy"
    Write-Host "         showing its latest run's verdict, metrics, sparkline."
    Write-Host "    r    Recent runs picker - numbered list of last 10 runs across strategies;"
    Write-Host "         open any dashboard by number."
    Write-Host "    c    Compare last 2 runs of active strategy. QuantStats multi-strategy"
    Write-Host "         report with SPY benchmark overlay."
    Write-Host ""
    Write-Host "  STRATEGY (create / edit)" -ForegroundColor Yellow
    Write-Host "    ns   New strategy. Prompts snake_case name + PascalCase class, writes"
    Write-Host "         pre-filled scaffold, opens in editor, validates (import + runtime"
    Write-Host "         smoke test on smoke_5) on save-close, registers in yaml."
    Write-Host "    ne   Edit active strategy source. Opens .py, re-validates on save-close."
    Write-Host "    nc   Clone strategy. Copies source file + yaml params under new name/class."
    Write-Host "    nd   Delete strategy. Moves source to _archive/, offers audit cleanup."
    Write-Host "         REFUSES to delete canaries (rand/overfit/leak/survivor)."
    Write-Host "    pp   Promote latest run's params to yaml defaults. Shows param diff,"
    Write-Host "         confirms, validates. Warns on FRAGILE verdicts (those failed gauntlet)."
    Write-Host "    s    Change active strategy via numbered picker. Persists across launches."
    Write-Host "    u    Change active universe via numbered picker. Persists across launches."
    Write-Host ""
    Write-Host "  RUN (compute)" -ForegroundColor Yellow
    Write-Host "    1    Quick optimize - 20 Optuna trials on active strategy, no tearsheet."
    Write-Host "         Fast param-space probe; shows fitness chart + parcoords."
    Write-Host "    2    Quick walk-forward - 10 trials/window, IS/OOS per window, plotext"
    Write-Host "         bar chart comparing IS vs OOS PF per window at end."
    Write-Host "    3    Run + dashboard. Baseline backtest on active strategy + universe."
    Write-Host "         Generates audit row, dashboard, quantstats tearsheet. ~1-2 min."
    Write-Host "    3r   Run + robustness. (3) PLUS 500 MC sims + noise injection + LOSO"
    Write-Host "         + entry-delay + regime tests. Produces FRAGILE/MARGINAL/ROBUST verdict."
    Write-Host "         ~3-5 min."
    Write-Host "    3f   Run --full. (3r) PLUS Optuna optimize + walk-forward + cost sweep."
    Write-Host "         Asks for confirmation (takes ~10 min)."
    Write-Host ""
    Write-Host "  HEALTH (diagnostics)" -ForegroundColor Yellow
    Write-Host "    d    Re-run tradelab doctor. Verifies env, deps, config, strategies,"
    Write-Host "         cache, audit DB, canary verdicts."
    Write-Host "    !    Run canary suite - 4 canaries (rand_canary, overfit_canary,"
    Write-Host "         leak_canary, survivor_canary). Must NOT return ROBUST - these"
    Write-Host "         are deliberately broken and flag tool trust if they pass."
    Write-Host "    g    Gate-check. Pearson correlation between indicator gates."
    Write-Host "         Flags redundant (|r|>0.7) vs independent (|r|<0.2) combinations."
    Write-Host ""
    Write-Host "  UTIL" -ForegroundColor Yellow
    Write-Host "    4    Rebuild reports/index.html from audit DB."
    Write-Host "    5    Open optuna-dashboard URL (http://127.0.0.1:8080) in browser."
    Write-Host "    6    Open reports/index.html in browser."
    Write-Host "    k    Kill optuna-dashboard background server on :8080."
    Write-Host "    i    Install Desktop shortcut to tradelab-launch.bat."
    Write-Host "    z    Cleanup orphan run folders. Lists reports/ folders not in audit"
    Write-Host "         DB, lets you pick which to delete."
    Write-Host "    x    Custom tradelab command. Type any 'tradelab <args>' without"
    Write-Host "         leaving the launcher."
    Write-Host ""
    Write-Host "  DATA" -ForegroundColor Yellow
    Write-Host "    rf   Refresh parquet cache for active universe via Twelve Data."
    Write-Host "         Writes to .cache/ohlcv/1D/<symbol>.parquet. Non-forced: skips symbols"
    Write-Host "         whose cache is already fresh. Works on the paid TD tier quota."
    Write-Host "    rb   Toggle the startup refresh prompt (B). When ON and cache is older"
    Write-Host "         than the stale threshold (default 24h), the launcher asks to refresh"
    Write-Host "         on boot. Default: ON."
    Write-Host "    rp   Toggle the pre-run refresh prompt (C). When ON, before options 3/3r/3f"
    Write-Host "         run, the launcher checks cache age and offers to refresh. Default: OFF."
    Write-Host ""
    Write-Host "  EXTERNAL" -ForegroundColor Yellow
    Write-Host "    #    Launch the AlgoTrade Command Center (C:\TradingScripts\Launch_Dashboard.bat)."
    Write-Host "         Opens the Alpaca-connected browser UI on http://localhost:8877. If already"
    Write-Host "         running (port 8877 bound), just opens the URL without starting a 2nd server."
    Write-Host ""
    Write-Host "  META" -ForegroundColor Yellow
    Write-Host "    q    Quit. Optuna-dashboard keeps running in background (use k to stop)."
    Write-Host "    h    This help glossary."
    Write-Host ""
    Write-Host "  State file:     .cache/launcher-state.json  (active strategy, universe)" -ForegroundColor DarkGray
    Write-Host "  YAML backups:   .cache/yaml_backups/        (last 10 kept, rotating)" -ForegroundColor DarkGray
    Write-Host "  Optuna studies: .cache/optuna_studies.db    (browsable via optuna-dashboard)" -ForegroundColor DarkGray
    Write-Host ""
}

function Invoke-GateCheckMenu {
    param([string]$universe, $meta)
    # Resolve symbols from active universe (first 5), default fallback otherwise
    $symbols = "NVDA,MSFT,AAPL,META,AVGO"
    if ($meta -and $meta.universes_full -and $meta.universes_full.$universe) {
        $syms = @($meta.universes_full.$universe | Where-Object { $_ -ne "SPY" })
        if ($syms.Count -gt 0) {
            $take = [math]::Min($syms.Count, 6)
            $symbols = ($syms | Select-Object -First $take) -join ","
        }
    }
    Write-Host ""
    Write-Host "  gate-check: active universe = $universe" -ForegroundColor Cyan
    $sIn = Read-Host "  symbols (comma, blank = $symbols)"
    if ($sIn) { $symbols = $sIn }
    $defaultGates = "adr_pct_20d,relative_volume_20d,sigma_spike,minervini_template"
    $gIn = Read-Host "  gates (comma, blank = $defaultGates)"
    $gates = if ($gIn) { $gIn } else { $defaultGates }

    & $Tradelab gate-check --symbols $symbols --gates $gates
}

# -------- previous-run metrics for regression detection -------------------
function Get-PreviousRunMetrics {
    param([string]$strategy)
    $script = @"
import json, sys
from pathlib import Path
from tradelab.audit.history import list_runs
from tradelab.results import BacktestResult
rows = list_runs(strategy='$strategy', limit=1)
if not rows:
    print(json.dumps(None)); sys.exit(0)
r = rows[0]
out = {'run_id': r.run_id[:8], 'verdict': (r.verdict or 'UNKNOWN').upper(),
       'pf': None, 'max_dd': None, 'ret_pct': None}
if r.report_card_html_path:
    try:
        folder = Path(r.report_card_html_path).parent
        jf = folder / 'backtest_result.json'
        if jf.exists():
            bt = BacktestResult.model_validate_json(jf.read_text(encoding='utf-8'))
            out['pf'] = bt.metrics.profit_factor
            out['max_dd'] = bt.metrics.max_drawdown_pct
            out['ret_pct'] = bt.metrics.pct_return
    except Exception:
        pass
print(json.dumps(out))
"@
    $json = & $VenvPython -c $script 2>$null
    if ($LASTEXITCODE -eq 0 -and $json) {
        $obj = $json | ConvertFrom-Json
        if ($obj) { return $obj }
    }
    return $null
}

# Verdict severity (higher = worse). Used for regression detection.
$VerdictRank = @{
    "ROBUST" = 0; "MARGINAL" = 1; "INCONCLUSIVE" = 2;
    "UNEVALUATED" = 2; "UNKNOWN" = 2; "FRAGILE" = 3
}

function Show-RegressionReport {
    param($prev, [string]$strategy)
    if (-not $prev) { return }
    # Load current run's latest metrics via the same helper
    $curr = Get-PreviousRunMetrics -strategy $strategy
    if (-not $curr -or $curr.run_id -eq $prev.run_id) {
        # No new run recorded -> regression check doesn't apply
        return
    }
    $warnings = @()

    if ($prev.pf -ne $null -and $curr.pf -ne $null -and $prev.pf -gt 0) {
        $drop = ($prev.pf - $curr.pf) / $prev.pf
        if ($drop -ge 0.10) {
            $warnings += ("PF dropped {0:P1} ({1:N2} -> {2:N2})" -f $drop, $prev.pf, $curr.pf)
        }
    }
    if ($prev.max_dd -ne $null -and $curr.max_dd -ne $null) {
        $prevAbs = [math]::Abs($prev.max_dd)
        $currAbs = [math]::Abs($curr.max_dd)
        if ($prevAbs -gt 0 -and ($currAbs - $prevAbs) / $prevAbs -ge 0.25) {
            $warnings += ("MaxDD worsened by {0:P0} ({1:N1}% -> {2:N1}%)" -f (($currAbs - $prevAbs) / $prevAbs), $prev.max_dd, $curr.max_dd)
        }
    }
    $pRank = $VerdictRank[$prev.verdict]; if ($null -eq $pRank) { $pRank = 2 }
    $cRank = $VerdictRank[$curr.verdict]; if ($null -eq $cRank) { $cRank = 2 }
    if ($cRank -gt $pRank) {
        $warnings += ("Verdict degraded: {0} -> {1}" -f $prev.verdict, $curr.verdict)
    }

    Write-Host ""
    if ($warnings.Count -gt 0) {
        Write-Host "===== REGRESSION FLAGS =====" -ForegroundColor Red
        foreach ($w in $warnings) { Write-Host "  ! $w" -ForegroundColor Red }
        Write-Host "  (compared against prior run $($prev.run_id))" -ForegroundColor DarkGray
    } else {
        $deltaPf = "n/a"
        if ($prev.pf -ne $null -and $curr.pf -ne $null) {
            $deltaPf = ("{0:+0.00;-0.00;0.00}" -f ($curr.pf - $prev.pf))
        }
        Write-Host "[ok]  no regressions vs prior run $($prev.run_id) (dPF=$deltaPf  verdict: $($prev.verdict) -> $($curr.verdict))" -ForegroundColor Green
    }
}

# -------- launcher state persistence (remembers active strategy/universe) --
$StateFile = Join-Path $TradelabRoot ".cache\launcher-state.json"

function Get-LauncherState {
    if (Test-Path $StateFile) {
        try { return (Get-Content $StateFile -Raw | ConvertFrom-Json) } catch {}
    }
    return $null
}

function Save-LauncherState {
    param(
        [string]$strategy,
        [string]$universe,
        [Nullable[bool]]$refreshOnBoot = $null,
        [Nullable[bool]]$refreshPreRun = $null,
        [Nullable[int]]$staleThresholdHours = $null
    )
    try {
        $dir = Split-Path $StateFile -Parent
        if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
        # Preserve any existing values we aren't explicitly overwriting
        $existing = Get-LauncherState
        $rob = if ($null -ne $refreshOnBoot) { [bool]$refreshOnBoot }
                elseif ($existing -and $null -ne $existing.refreshOnBoot) { [bool]$existing.refreshOnBoot }
                else { $true }
        $rpr = if ($null -ne $refreshPreRun) { [bool]$refreshPreRun }
                elseif ($existing -and $null -ne $existing.refreshPreRun) { [bool]$existing.refreshPreRun }
                else { $false }
        $sth = if ($null -ne $staleThresholdHours) { [int]$staleThresholdHours }
                elseif ($existing -and $null -ne $existing.staleThresholdHours) { [int]$existing.staleThresholdHours }
                else { 24 }
        $obj = @{
            activeStrategy = $strategy
            activeUniverse = $universe
            refreshOnBoot = $rob
            refreshPreRun = $rpr
            staleThresholdHours = $sth
            savedAt = (Get-Date -Format "yyyy-MM-ddTHH:mm:ss")
        }
        $obj | ConvertTo-Json | Set-Content -Path $StateFile -Encoding UTF8
    } catch {}
}

# -------- run wrapper: tees console output into the new run folder ---------
function Invoke-TradelabRun {
    param(
        [string]$strategy,
        [string]$universe,
        [string]$startDate,
        [string[]]$extraArgs
    )
    $today = (Get-Date -Format 'yyyy-MM-dd')
    $tempLog = [System.IO.Path]::GetTempFileName()
    Write-Host "[run]   $strategy on $universe (start=$startDate, end=$today)" -ForegroundColor Cyan

    # Pre-run refresh prompt (C) -- if enabled AND data is stale, prompt before
    # burning compute on a backtest that'd use old data.
    if ($script:refreshPreRun) {
        $df = Get-DataFreshness
        if ($df -and $df.age_hours -ge $script:staleThresholdHours) {
            $ageStr = if ($df.age_hours -lt 24) { "{0:N1}h" -f $df.age_hours }
                       else { "{0:N1}d" -f ($df.age_hours / 24) }
            Write-Host "[stale] data is $ageStr old (threshold $($script:staleThresholdHours)h)" -ForegroundColor Yellow
            $ans = (Read-Host "         refresh before running? (Y/n)").Trim().ToLower()
            if (-not $ans -or $ans -eq 'y') {
                Invoke-DataRefresh -universe $universe | Out-Null
            }
        }
    }

    # Snapshot prior run's metrics BEFORE running so we can detect regression.
    $prev = Get-PreviousRunMetrics -strategy $strategy

    $baseArgs = @("run", $strategy, "--universe", $universe,
                   "--start", $startDate, "--end", $today,
                   "--no-open-dashboard")
    if ($extraArgs) { $baseArgs += $extraArgs }

    # Tee-Object captures stdout+stderr to the log while still printing live.
    & $Tradelab @baseArgs 2>&1 | Tee-Object -FilePath $tempLog

    # Find the new run folder and move the captured log into it as console.log
    $newFolder = Get-ChildItem -Path (Join-Path $TradelabRoot "reports") -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -like "$strategy`_*" -and (Test-Path (Join-Path $_.FullName "dashboard.html")) } |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($newFolder) {
        try {
            Move-Item $tempLog (Join-Path $newFolder.FullName "console.log") -Force
            Write-Host "[log]   saved: $($newFolder.FullName)\console.log" -ForegroundColor DarkGray
        } catch { Remove-Item $tempLog -ErrorAction SilentlyContinue }
    } else {
        Remove-Item $tempLog -ErrorAction SilentlyContinue
    }

    # Regenerate both index + overview, then open the new run's dashboard
    & $Tradelab rebuild-index --no-open | Out-Null
    & $Tradelab overview --no-open | Out-Null

    # Regression detection vs prior run
    Show-RegressionReport -prev $prev -strategy $strategy

    Open-LatestRunDashboard $strategy
}

# -------- orphan folder cleanup --------------------------------------------
function Get-OrphanFolders {
    $script = @"
import json
from pathlib import Path
from tradelab.audit.history import list_runs
reports = Path('reports')
if not reports.exists():
    print('[]'); raise SystemExit
known = set()
for r in list_runs(limit=10000):
    if r.report_card_html_path:
        try:
            known.add(str(Path(r.report_card_html_path).parent.resolve()).replace('\\', '/').lower())
        except Exception:
            pass
orphans = []
for entry in sorted(reports.iterdir()):
    if not entry.is_dir():
        continue
    # skip the per-run folder if the audit DB references it
    full = str(entry.resolve()).replace('\\', '/').lower()
    if full in known:
        continue
    orphans.append({'name': entry.name, 'path': str(entry).replace('\\', '/')})
print(json.dumps(orphans))
"@
    $json = & $VenvPython -c $script 2>$null
    if ($LASTEXITCODE -eq 0 -and $json) { return @($json | ConvertFrom-Json) }
    return @()
}

function Invoke-CleanupOrphans {
    $orphans = Get-OrphanFolders
    if ($orphans.Count -eq 0) {
        Write-Host "[ok]   reports/ has no orphan folders." -ForegroundColor Green; return
    }
    Write-Host ""
    Write-Host "  orphan folders in reports/ (not referenced by audit DB):" -ForegroundColor Cyan
    for ($i = 0; $i -lt $orphans.Count; $i++) {
        Write-Host ("    {0,2}) {1}" -f ($i + 1), $orphans[$i].name)
    }
    Write-Host ""
    $sel = (Read-Host "  delete which? (a=all, numbers comma-sep, blank=cancel)").Trim().ToLower()
    if (-not $sel) { Write-Host "[skip] cancelled." -ForegroundColor Yellow; return }

    $toDelete = @()
    if ($sel -eq "a") {
        $toDelete = $orphans
    } else {
        foreach ($tok in ($sel -split ',')) {
            $n = 0
            if ([int]::TryParse($tok.Trim(), [ref]$n)) {
                if ($n -ge 1 -and $n -le $orphans.Count) { $toDelete += $orphans[$n - 1] }
            }
        }
    }
    if ($toDelete.Count -eq 0) { Write-Host "[skip] nothing selected." -ForegroundColor Yellow; return }

    $confirm = (Read-Host "  delete $($toDelete.Count) folder(s)? (y/N)").Trim().ToLower()
    if ($confirm -notmatch '^y') { Write-Host "[skip] cancelled." -ForegroundColor Yellow; return }

    foreach ($o in $toDelete) {
        try {
            Remove-Item -Recurse -Force $o.path -ErrorAction Stop
            Write-Host "[del]  $($o.name)" -ForegroundColor Green
        } catch {
            Write-Host "[fail] $($o.name): $($_.Exception.Message)" -ForegroundColor Red
        }
    }
    & $Tradelab rebuild-index --no-open | Out-Null
    & $Tradelab overview --no-open | Out-Null
}

function Get-RecentRuns([int]$limit = 10) {
    $script = @"
import json
from pathlib import Path
from tradelab.audit.history import list_runs
rows = list_runs(limit=$limit)
out = []
for r in rows:
    folder = ''
    if r.report_card_html_path:
        try:
            folder = str(Path(r.report_card_html_path).parent).replace('\\', '/')
        except Exception:
            pass
    out.append({
        'id': r.run_id[:8], 'strategy': r.strategy_name or '',
        'when': (r.timestamp_utc or '')[:16],
        'verdict': (r.verdict or 'UNKNOWN'), 'folder': folder,
    })
print(json.dumps(out))
"@
    $json = & $VenvPython -c $script 2>$null
    if ($LASTEXITCODE -eq 0 -and $json) { return @($json | ConvertFrom-Json) }
    return @()
}

function Get-LastTwoOfStrategy([string]$strategy) {
    $script = @"
import json
from pathlib import Path
from tradelab.audit.history import list_runs
rows = list_runs(strategy='$strategy', limit=2)
out = []
for r in rows:
    if r.report_card_html_path:
        out.append(str(Path(r.report_card_html_path).parent).replace('\\', '/'))
print(json.dumps(out))
"@
    $json = & $VenvPython -c $script 2>$null
    if ($LASTEXITCODE -eq 0 -and $json) { return @($json | ConvertFrom-Json) }
    return @()
}

function Open-LatestRunDashboard([string]$strategy) {
    $latest = Get-ChildItem -Path (Join-Path $TradelabRoot "reports") -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -like "$strategy`_*" -and (Test-Path (Join-Path $_.FullName "dashboard.html")) } |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($latest) {
        $dashPath = Join-Path $latest.FullName "dashboard.html"
        Write-Host "[open]  $dashPath" -ForegroundColor Cyan
        Start-Process $dashPath
    }
}

function Install-DesktopShortcut {
    $desktop = [Environment]::GetFolderPath("Desktop")
    $lnk = Join-Path $desktop "tradelab launcher.lnk"
    $target = Join-Path $TradelabRoot "tradelab-launch.bat"
    if (-not (Test-Path $target)) {
        Write-Host "[fail] launcher.bat not found at $target" -ForegroundColor Red; return
    }
    try {
        $wsh = New-Object -ComObject WScript.Shell
        $s = $wsh.CreateShortcut($lnk)
        $s.TargetPath = $target
        $s.WorkingDirectory = $TradelabRoot
        $s.Description = "tradelab environment launcher"
        # Line-chart icon from imageres.dll; falls back silently if unavailable
        $s.IconLocation = "$env:SystemRoot\System32\imageres.dll,76"
        $s.Save()
        Write-Host "[ok]   desktop shortcut installed: $lnk" -ForegroundColor Green
    } catch {
        Write-Host "[fail] $($_.Exception.Message)" -ForegroundColor Red
    }
}

function Select-FromList([string]$title, [array]$items, [string]$labelProp = $null) {
    if (-not $items -or $items.Count -eq 0) {
        Write-Host "[empty] no items" -ForegroundColor Yellow; return $null
    }
    Write-Host ""
    Write-Host "  $title" -ForegroundColor Cyan
    for ($i = 0; $i -lt $items.Count; $i++) {
        if ($labelProp) { $label = $items[$i].$labelProp } else { $label = $items[$i] }
        Write-Host ("    {0,2}) {1}" -f ($i + 1), $label)
    }
    $raw = (Read-Host "  number (or blank to cancel)").Trim()
    if (-not $raw) { return $null }
    $n = 0
    if (-not [int]::TryParse($raw, [ref]$n)) { return $null }
    if ($n -lt 1 -or $n -gt $items.Count) { return $null }
    return $items[$n - 1]
}

function Show-StrategyPicker($meta) {
    $items = @($meta.strategies | ForEach-Object {
        [pscustomobject]@{ name = $_.name; label = "$($_.name)  [$($_.status)]  $($_.description)" }
    })
    $pick = Select-FromList "active strategy" $items "label"
    if ($pick) { return $pick.name }
    return $null
}

function Show-UniversePicker($meta) {
    $items = @($meta.universes)
    return Select-FromList "active universe" $items
}

function Show-RecentRunsPicker {
    $runs = Get-RecentRuns 10
    if ($runs.Count -eq 0) { Write-Host "[empty] no runs in audit DB yet"; return }
    $items = @($runs | ForEach-Object {
        $v = $_.verdict.PadRight(12)
        [pscustomobject]@{ folder = $_.folder;
            label = "$($_.when)  $v  $($_.strategy)  [$($_.id)]" }
    })
    $pick = Select-FromList "recent runs" $items "label"
    if ($pick -and $pick.folder) {
        $dash = Join-Path $pick.folder "dashboard.html"
        if (Test-Path $dash) { Start-Process $dash }
        else { Write-Host "[warn] dashboard.html missing in $($pick.folder)" -ForegroundColor Yellow }
    }
}

function Invoke-CompareLastTwo([string]$strategy) {
    $folders = Get-LastTwoOfStrategy $strategy
    if ($folders.Count -lt 2) {
        Write-Host "[skip] need at least 2 audit rows for '$strategy' (have $($folders.Count))" -ForegroundColor Yellow
        return
    }
    Write-Host "[cmp]  comparing last 2 runs of $strategy :"
    $folders | ForEach-Object { Write-Host "         - $_" }
    & $Tradelab compare $folders[0] $folders[1]
}

function Invoke-CanarySuite {
    if (-not (Test-Path $RunCanaries)) {
        Write-Host "[skip] $RunCanaries not found" -ForegroundColor Yellow; return
    }
    Write-Host "[run]  invoking canary suite (this may take a minute)..." -ForegroundColor Yellow
    & $VenvPython $RunCanaries
}

# --- startup sequence ------------------------------------------------
Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "   tradelab environment launcher" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

Invoke-DoctorStartupCheck
Start-OptunaDashboard

Write-Host "[step]  rebuilding reports\index.html..." -ForegroundColor Yellow
& $Tradelab rebuild-index --no-open | Out-Null
Write-Host "[ok]    index rebuilt" -ForegroundColor Green

if (Test-Path $IndexHtml) {
    Start-Process $IndexHtml
    Start-Sleep -Milliseconds 400
}
Start-Process $DashboardUrl

$meta = Get-TradelabMeta
if (-not $meta) {
    Write-Host "[warn]  could not load tradelab meta -- strategy/universe picker disabled" -ForegroundColor Yellow
} else {
    $gc = if ($meta.git_commit) { $meta.git_commit.Substring(0, [math]::Min(7, $meta.git_commit.Length)) } else { "unknown" }
    Write-Host ("[prov]  tradelab v{0}  git {1}  config: {2}" -f $meta.version, $gc, $meta.config_path) -ForegroundColor DarkGray
}

# Restore saved selection from last session, if any.
$saved = Get-LauncherState
if ($saved -and $saved.activeStrategy) {
    $activeStrategy = $saved.activeStrategy
    $activeUniverse = $saved.activeUniverse
    $refreshOnBoot = if ($null -ne $saved.refreshOnBoot) { [bool]$saved.refreshOnBoot } else { $true }
    $refreshPreRun = if ($null -ne $saved.refreshPreRun) { [bool]$saved.refreshPreRun } else { $false }
    $staleThresholdHours = if ($null -ne $saved.staleThresholdHours) { [int]$saved.staleThresholdHours } else { 24 }
    Write-Host "[load]  restored previous: strategy=$activeStrategy universe=$activeUniverse" -ForegroundColor DarkGray
} else {
    $activeStrategy = "s2_pocket_pivot"
    $activeUniverse = "smoke_5"
    $refreshOnBoot = $true
    $refreshPreRun = $false
    $staleThresholdHours = 24
}

# Startup refresh prompt (B) -- if enabled AND data is beyond stale threshold,
# offer to refresh before the user starts working.
if ($refreshOnBoot) {
    $df0 = Get-DataFreshness
    if ($df0 -and $df0.age_hours -ge $staleThresholdHours) {
        $ageStr0 = if ($df0.age_hours -lt 24) { "{0:N1}h" -f $df0.age_hours }
                    else { "{0:N1}d" -f ($df0.age_hours / 24) }
        Write-Host ""
        Write-Host "[stale] parquet cache is $ageStr0 old (threshold $staleThresholdHours h)" -ForegroundColor Yellow
        $ans = (Read-Host "         refresh via Twelve Data now for universe '$activeUniverse'? (Y/n)").Trim().ToLower()
        if (-not $ans -or $ans -eq 'y') {
            Invoke-DataRefresh -universe $activeUniverse | Out-Null
        } else {
            Write-Host "[skip]   leaving cache as-is (toggle off with 'rb' to stop asking)" -ForegroundColor DarkGray
        }
    }
}

# Start date: prefer yaml default from meta; fall back to 2024-04-08.
if ($meta -and $meta.data_start) { $activeStart = $meta.data_start }
else { $activeStart = "2024-04-08" }

# --- interactive menu ------------------------------------------------
function Show-Menu {
    Write-Host ""
    # --- Prominent AlgoTrade Command Center launcher ---
    $ccState = if (Test-CommandCenterRunning) { "running" } else { "offline" }
    $ccColor = if ($ccState -eq "running") { "Green" } else { "Magenta" }
    Write-Host "  >>  " -ForegroundColor $ccColor -NoNewline
    Write-Host "[ # ] " -ForegroundColor White -NoNewline
    Write-Host "-> AlgoTrade Command Center (Alpaca)  " -ForegroundColor $ccColor -NoNewline
    Write-Host "[$ccState]" -ForegroundColor DarkGray
    Write-Host ""
    Write-Host "================================================================" -ForegroundColor Cyan
    Write-Host ("  active:  strategy=[{0}]  universe=[{1}]" -f $activeStrategy, $activeUniverse) -ForegroundColor White
    # State line: latest run age + verdict for the active strategy
    $li = Get-LatestRunInfo -strategy $activeStrategy
    if ($li) {
        $ageStr = if ($li.age_days -eq $null) { "unknown" }
                  elseif ($li.age_days -lt 1) { [string][math]::Round($li.age_days * 24, 1) + "h" }
                  else { [string][math]::Round($li.age_days, 1) + "d" }
        $vColor = switch ($li.verdict) {
            "ROBUST" { "Green" }
            "MARGINAL" { "Yellow" }
            "FRAGILE" { "Red" }
            default { "DarkGray" }
        }
        Write-Host ("  last run: {0} ago  ." -f $ageStr) -ForegroundColor DarkGray -NoNewline
        Write-Host " verdict: " -ForegroundColor DarkGray -NoNewline
        Write-Host $li.verdict -ForegroundColor $vColor
    } else {
        Write-Host "  last run: no runs yet for this strategy" -ForegroundColor DarkGray
    }
    # Data freshness: age of newest CSV in data_dir. 24h is the user's
    # threshold for "fresh enough for active research."
    $df = Get-DataFreshness
    if ($df) {
        $dAgeStr = if ($df.age_hours -lt 24) { [string][math]::Round($df.age_hours, 1) + "h" }
                    else { [string][math]::Round($df.age_hours / 24, 1) + "d" }
        $dColor = if ($df.age_hours -lt 24) { "DarkGray" }
                   elseif ($df.age_hours -lt 72) { "Yellow" }
                   else { "Red" }
        Write-Host "  data:     " -ForegroundColor DarkGray -NoNewline
        Write-Host "$dAgeStr old" -ForegroundColor $dColor -NoNewline
        Write-Host " (newest: $($df.newest), $($df.n_files) files)" -ForegroundColor DarkGray
    }
    Write-Host "================================================================" -ForegroundColor Cyan

    Write-Host "  HOME          t   open latest tearsheet (richest: robustness > dashboard > qs)"
    Write-Host "                ts  open quantstats tearsheet (compact)"
    Write-Host "                o   portfolio overview (all strategies)"
    Write-Host "                r   recent runs picker"
    Write-Host "                c   compare last 2 runs of active strategy"
    Write-Host ""
    Write-Host "  STRATEGY      ns  new strategy          (scaffold + editor + register + validate)"
    Write-Host "                ne  edit active strategy  (opens source, revalidates on save)"
    Write-Host "                nc  clone strategy        (copy source + params, new name)"
    Write-Host "                nd  delete strategy       (archives source, optional audit cleanup)"
    Write-Host "                pp  promote run params    (latest run's params -> yaml defaults)"
    Write-Host "                s   change active strategy"
    Write-Host "                u   change active universe"
    Write-Host ""
    Write-Host "  RUN           1   quick optimize       (active strategy, 20 trials)"
    Write-Host "                2   quick walk-forward   (10 trials/win)"
    Write-Host "                3   run + dashboard      (baseline, current params)  ~1-2 min"
    Write-Host "                3r  run + robustness     (+ MC / LOSO / regime)      ~3-5 min"
    Write-Host "                3f  run --full           (+ optuna + wf + cost)      ~10 min"
    Write-Host ""
    Write-Host "  HEALTH        d   re-run doctor"
    Write-Host "                !   run canary suite"
    Write-Host "                g   gate-check  (indicator gate correlation)"
    Write-Host ""
    $rbState = if ($refreshOnBoot) { "on" } else { "off" }
    $rpState = if ($refreshPreRun) { "on" } else { "off" }
    Write-Host "  DATA          rf  refresh active universe now (Twelve Data)"
    Write-Host "                rb  toggle startup-refresh prompt  [$rbState]"
    Write-Host "                rp  toggle pre-run-refresh prompt  [$rpState]"
    Write-Host ""
    Write-Host "  UTIL          4   rebuild index       5   open optuna-dash      6   open index"
    Write-Host "                k   kill optuna-dash    i   desktop shortcut"
    Write-Host "                z   cleanup orphans     x   custom tradelab command"
    Write-Host ""
    Write-Host "                h   help (full key glossary)"
    Write-Host "                q   quit"
}

while ($true) {
    Show-Menu
    $choice = (Read-Host "  choice").Trim()
    if (-not $choice) { continue }
    $lc = $choice.ToLower()

    switch -Regex ($lc) {
        "^1$" { & $Tradelab optimize $activeStrategy --trials 20 --no-tearsheet }
        "^2$" { & $Tradelab wf $activeStrategy --trials 10 }
        "^3$" {
            Invoke-TradelabRun -strategy $activeStrategy -universe $activeUniverse `
                -startDate $activeStart -extraArgs @()
        }
        "^3r$" {
            Invoke-TradelabRun -strategy $activeStrategy -universe $activeUniverse `
                -startDate $activeStart -extraArgs @("--robustness")
        }
        "^3f$" {
            $ans = (Read-Host "  [confirm] full run (optuna + wf + cost-sweep + robustness) takes ~10 min. proceed? (y/N)").Trim().ToLower()
            if ($ans -match '^y') {
                Invoke-TradelabRun -strategy $activeStrategy -universe $activeUniverse `
                    -startDate $activeStart -extraArgs @("--full")
            } else {
                Write-Host "[skip]  cancelled." -ForegroundColor Yellow
            }
        }
        "^4$" {
            & $Tradelab rebuild-index --no-open
            Write-Host "[ok] refresh the index browser tab." -ForegroundColor Green
        }
        "^5$" { Start-Process $DashboardUrl }
        "^6$" { if (Test-Path $IndexHtml) { Start-Process $IndexHtml } }
        "^c$" { Invoke-CompareLastTwo $activeStrategy }
        "^r$" { Show-RecentRunsPicker }
        "^rf$" { Invoke-DataRefresh -universe $activeUniverse | Out-Null }
        "^rb$" {
            $refreshOnBoot = -not $refreshOnBoot
            Save-LauncherState $activeStrategy $activeUniverse -refreshOnBoot $refreshOnBoot -refreshPreRun $refreshPreRun -staleThresholdHours $staleThresholdHours
            $state = if ($refreshOnBoot) { "ON" } else { "OFF" }
            Write-Host "[ok]   refresh-on-boot prompt: $state" -ForegroundColor Green
        }
        "^rp$" {
            $refreshPreRun = -not $refreshPreRun
            Save-LauncherState $activeStrategy $activeUniverse -refreshOnBoot $refreshOnBoot -refreshPreRun $refreshPreRun -staleThresholdHours $staleThresholdHours
            $state = if ($refreshPreRun) { "ON" } else { "OFF" }
            Write-Host "[ok]   refresh-pre-run prompt: $state" -ForegroundColor Green
        }
        "^t$" { Invoke-OpenTearsheet -strategy $activeStrategy -prefer "richest" }
        "^ts$" { Invoke-OpenTearsheet -strategy $activeStrategy -prefer "quantstats" }
        "^ns$" { Invoke-NewStrategy }
        "^ne$" { Invoke-EditActive }
        "^nc$" { Invoke-CloneStrategy }
        "^nd$" { Invoke-DeleteStrategy }
        "^pp$" { Invoke-PromoteParams }
        "^s$" {
            if ($meta) {
                $new = Show-StrategyPicker $meta
                if ($new) { $activeStrategy = $new; Save-LauncherState $activeStrategy $activeUniverse }
            } else { Write-Host "[skip] meta not loaded" -ForegroundColor Yellow }
        }
        "^u$" {
            if ($meta) {
                $new = Show-UniversePicker $meta
                if ($new) { $activeUniverse = $new; Save-LauncherState $activeStrategy $activeUniverse }
            } else { Write-Host "[skip] meta not loaded" -ForegroundColor Yellow }
        }
        "^g$" { Invoke-GateCheckMenu -universe $activeUniverse -meta $meta }
        "^d$" { Invoke-DoctorStartupCheck }
        "^!$" { Invoke-CanarySuite }
        "^k$" { Stop-OptunaDashboard }
        "^i$" { Install-DesktopShortcut }
        "^o$" { & $Tradelab overview }
        "^z$" { Invoke-CleanupOrphans }
        "^x$" {
            $cmd = Read-Host "  tradelab <args>"
            if ($cmd) { & $Tradelab @($cmd -split '\s+') }
        }
        "^q$" { break }
        "^h$" { Show-HelpGlossary }
        "^#$" { Invoke-AlgoTradeCenter }
        default { Write-Host "[?] unknown choice: '$choice'" -ForegroundColor Yellow }
    }
}

Write-Host ""
Write-Host "launcher closed." -ForegroundColor Cyan
Write-Host "optuna-dashboard may still be running in the background." -ForegroundColor DarkGray
Write-Host "to stop it later: re-launch and press 'k', or use Task Manager." -ForegroundColor DarkGray
Write-Host ""

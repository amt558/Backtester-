#Requires -Version 5.1
<#
.SYNOPSIS
    THE merge gate. Mandatory before any merge onto the verdict engine.

.DESCRIPTION
    Runs all 4 checkpoints and exits non-zero if ANY fails:
      cp1  pytest tests/robustness/test_verdict.py        (expect 20/20)
      cp2  pytest -m canary_integration                   (expect 5/5)
      cp3  full pytest -> --junitxml -> scripts/gate_confine.py
           (the 3 tracked B2 delete-safety reds are CONFINED; any other
            failure, in any file, fails the gate)
      cp4  python -m tradelab.cli robustness viprasol_v83 --offline --expect FRAGILE
           (exit 0 = PASS; 2 = Q-B expectation mismatch; 1 = engine/input)

    A clean worktree is a PRECONDITION, not a checkpoint. The --deselect flag
    is permanently retired and must not be reintroduced.

    Run from the repo root:  pwsh -File scripts/gate.ps1
#>

$env:PYTHONUTF8 = "1"   # verdict reason strings contain <= / >= ; cp1252 stdout throws otherwise

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$cache = Join-Path $root ".cache"
if (-not (Test-Path $cache)) { New-Item -ItemType Directory -Path $cache -Force | Out-Null }

# Run one checkpoint. Hardened so a command that fails to LAUNCH (e.g. exe not
# found) can never inherit a stale $LASTEXITCODE=0 and be scored PASS:
#   - reset $LASTEXITCODE to $null first; a launched process overwrites it,
#   - a CommandNotFoundException is caught and scored FAIL,
#   - PASS requires an explicit exit code of exactly 0.
# The checkpoint command's output flows on the normal success stream (so it is
# captured by an outer `*>&1 | Tee-Object`); the pass/fail verdict is recorded
# in $script:failed rather than returned, so native stdout can never pollute a
# boolean return value.
$script:failed = @()

function Test-Checkpoint {
    param([string]$Name, [scriptblock]$Command)
    Write-Host "`n=== $Name ===" -ForegroundColor Cyan
    $global:LASTEXITCODE = $null
    try {
        & $Command
    } catch {
        Write-Host "$Name FAIL (failed to launch: $($_.Exception.Message))" -ForegroundColor Red
        $script:failed += $Name
        return
    }
    $code = $LASTEXITCODE
    if ($code -eq 0) {
        Write-Host "$Name PASS" -ForegroundColor Green
    } elseif ($null -eq $code) {
        Write-Host "$Name FAIL (no exit code recorded -- command did not launch)" -ForegroundColor Red
        $script:failed += $Name
    } else {
        Write-Host "$Name FAIL (exit $code)" -ForegroundColor Red
        $script:failed += $Name
    }
}

$junit = Join-Path $cache "full_suite_gate.xml"

Test-Checkpoint "cp1: verdict unit tests (expect 20/20)" {
    python -m pytest tests/robustness/test_verdict.py -q -p no:cacheprovider
}

Test-Checkpoint "cp2: canary integration (expect 5/5)" {
    python -m pytest -m canary_integration -q -p no:cacheprovider
}

Test-Checkpoint "cp3: full suite, B2 confinement" {
    # Delete any stale report first: a pytest that crashes before writing the
    # report must not let gate_confine.py pass on a previous run's XML.
    Remove-Item $junit -ErrorAction SilentlyContinue
    # pytest WILL exit non-zero here because the 3 B2 reds fail. That exit code
    # is expected -- the cp3 verdict is decided solely by gate_confine.py below,
    # which is the last command and therefore sets $LASTEXITCODE.
    python -m pytest --timeout=300 -p no:cacheprovider "--junitxml=$junit"
    python scripts/gate_confine.py "--junitxml=$junit"
}

Test-Checkpoint "cp4: robustness FRAGILE invariant (expect exit 0)" {
    python -m tradelab.cli robustness viprasol_v83 --offline --expect FRAGILE
}

Write-Host "`n========================================"
if ($failed.Count -gt 0) {
    Write-Host "MERGE GATE: FAIL -- $($failed -join ', ')" -ForegroundColor Red
    exit 1
}
Write-Host "MERGE GATE: PASS -- all 4 checkpoints green" -ForegroundColor Green
exit 0

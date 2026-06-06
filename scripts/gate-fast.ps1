#Requires -Version 5.1
<#
.SYNOPSIS
    DEV INNER LOOP ONLY -- NOT a merge gate.

.DESCRIPTION
    Fast feedback: cp1 / cp2 / cp4. It OMITS cp3 (the full-suite B2 confinement
    check), so it can never certify a merge. Use scripts/gate.ps1 before merging.

    Run from the repo root:  pwsh -File scripts/gate-fast.ps1
#>

$env:PYTHONUTF8 = "1"   # verdict reason strings contain <= / >= ; cp1252 stdout throws otherwise

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

Write-Host "########################################################" -ForegroundColor Yellow
Write-Host "#  gate-fast: DEV INNER LOOP ONLY -- NOT a merge gate. #" -ForegroundColor Yellow
Write-Host "#  cp3 (full-suite confinement) is SKIPPED.            #" -ForegroundColor Yellow
Write-Host "#  Run scripts/gate.ps1 before any merge.              #" -ForegroundColor Yellow
Write-Host "########################################################" -ForegroundColor Yellow

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

Test-Checkpoint "cp1: verdict unit tests (expect 20/20)" {
    python -m pytest tests/robustness/test_verdict.py -q -p no:cacheprovider
}

Test-Checkpoint "cp2: canary integration (expect 5/5)" {
    python -m pytest -m canary_integration -q -p no:cacheprovider
}

Test-Checkpoint "cp4: robustness FRAGILE invariant (expect exit 0)" {
    python -m tradelab.cli robustness viprasol_v83 --offline --expect FRAGILE
}

Write-Host "`n========================================"
Write-Host "REMINDER: gate-fast is NOT a merge gate (cp3 skipped)." -ForegroundColor Yellow
if ($failed.Count -gt 0) {
    Write-Host "gate-fast: FAIL -- $($failed -join ', ')" -ForegroundColor Red
    exit 1
}
Write-Host "gate-fast: PASS (cp1/cp2/cp4) -- still run scripts/gate.ps1 before merge." -ForegroundColor Green
exit 0

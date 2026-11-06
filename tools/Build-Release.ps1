# Copyright (C) 2026 the Playlist-bridge contributors (AUTHORS.md). SPDX-License-Identifier: GPL-3.0-only
<#
.SYNOPSIS
    One command, one wheel: runs the gates and builds release\playlist_bridge-<version>-py3-none-any.whl, the installable package.

.DESCRIPTION
    The version comes from the VERSION file and from nowhere else (python/setup.py reads it): it is stamped into the file name and
    the package metadata. Needs the dev tools: python -m pip install -e "python[dev]".
#>
param([switch]$SkipGates)

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$Version = (Get-Content (Join-Path $root "VERSION") -TotalCount 1).Trim()
if ($Version -cnotmatch '^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$') {
    throw "VERSION must be strict SemVer MAJOR.MINOR.PATCH (e.g. 0.1.4), got: '$Version'. See docs\VERSIONING.md"
}

function Invoke-Python {
    param([string[]]$PyArgs)
    # python tools print progress on stderr, which PowerShell would turn into a terminating error under "Stop"
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & python @PyArgs 2>&1 | ForEach-Object { Write-Output "$_" }
        $exit = $LASTEXITCODE
    } finally { $ErrorActionPreference = $previous }
    if ($exit -ne 0) { throw "python $($PyArgs -join ' ') failed" }
}

$out = Join-Path $root "release"
Push-Location (Join-Path $root "python")
try {
    if (-not $SkipGates) {
        Write-Output "Gates: format, lints, tests ..."
        Invoke-Python @("-m", "ruff", "format", "--check", ".")
        Invoke-Python @("-m", "ruff", "check", ".")
        Invoke-Python @("-m", "pytest", "-q")
    }
    Write-Output "Building (python -m build --wheel) ..."
    New-Item -ItemType Directory -Path $out -Force | Out-Null
    Invoke-Python @("-m", "build", "--wheel", "--outdir", $out, ".")
} finally { Pop-Location }

$wheel = Join-Path $out "playlist_bridge-$Version-py3-none-any.whl"
if (-not (Test-Path $wheel)) { throw "expected build output not found: $wheel" }
$hash = (Get-FileHash $wheel -Algorithm SHA256).Hash.ToLowerInvariant()
Write-Output "release: $wheel"
Write-Output "sha256:  $hash"

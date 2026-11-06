<#
.SYNOPSIS
    Enforces the Playlist-bridge versioning policy (docs/VERSIONING.md). Used by CI and runnable locally.

.DESCRIPTION
    Always: the version in python/pyproject.toml is strict MAJOR.MINOR.PATCH.
    Against the latest release tag: the version is either unchanged or exactly one valid bump
    (one component up, everything to its right reset to 0) of the latest tag.
    With -Tag (a release): the tag is the bare version, equals the version, and is greater than every existing release tag.
#>
param([string]$Tag)

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$strict = '^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$'

function Fail($m) { Write-Host "VERSION POLICY: $m" -ForegroundColor Red; exit 1 }

$pyproject = Get-Content (Join-Path $root "python/pyproject.toml") -Raw
if ($pyproject -notmatch '(?m)^version\s*=\s*"([^"]*)"') { Fail "no version in python/pyproject.toml" }
$version = $Matches[1]
if ($version -cnotmatch $strict) { Fail "version '$version' is not strict MAJOR.MINOR.PATCH" }

$tags = @(& git -C $root tag --list | Where-Object { $_ -cmatch $strict -and $_ -ne $Tag } |
    Sort-Object { [version]$_ })
$latest = if ($tags.Count) { $tags[-1] } else { $null }

if ($Tag) {
    if ($Tag -cnotmatch $strict) { Fail "tag '$Tag' must be the bare version X.Y.Z (no 'v' prefix, no suffix)" }
    if ($Tag -ne $version) { Fail "tag '$Tag' does not match the version '$version' in python/pyproject.toml" }
}

if ($latest) {
    $c = [version]$version; $l = [version]$latest
    $isBump = ($c.Major -eq $l.Major + 1 -and $c.Minor -eq 0 -and $c.Build -eq 0) -or
              ($c.Major -eq $l.Major -and $c.Minor -eq $l.Minor + 1 -and $c.Build -eq 0) -or
              ($c.Major -eq $l.Major -and $c.Minor -eq $l.Minor -and $c.Build -eq $l.Build + 1)
    if ($c -lt $l) { Fail "version $version is lower than the latest release $latest" }
    if ($Tag -and $c -le $l) { Fail "release $version must be greater than the latest release $latest" }
    if ($c -ne $l -and -not $isBump) { Fail "version $version is not a single valid bump of the latest release $latest" }
}

Write-Host "Version policy OK: version=$version latest-release=$(if ($latest) { $latest } else { 'none' })"

# Versioning

Playlist-bridge follows [Semantic Versioning 2.0.0](https://semver.org/spec/v2.0.0.html) strictly.

## The one source of truth

The `version = "MAJOR.MINOR.PATCH"` line of `python/pyproject.toml` holds the release number.
The build stamps it into the wheel's name and metadata; builds never write it. Do not hardcode a version anywhere else.

## Format

- Three non-negative integers separated by dots, no leading zeros (`0.1.4`, never `0.01.4`).
- No `v` prefix, no whitespace, no fourth component, no pre-release or build suffix.

## When to bump

While MAJOR is `0`, MINOR plays the role of "breaking".

| Bump | When |
| --- | --- |
| MAJOR | Stable release, or an intentional full break (1.0.0 and after) |
| MINOR | A new feature |
| PATCH | Bug fix or internal change |

A bump increases exactly one component and resets the ones to its right to `0`. Versions only go up; a published version is never reused or edited.

## Releasing

Releases are cut by CI from a tag. Do not build or upload the wheel by hand.

1. Edit `version` in `python/pyproject.toml` (one valid bump of the latest release) and merge it to `main` with the title `chore: version X.Y.Z`.
2. Tag that commit `X.Y.Z` (bare version, no `v`) and push the tag.
3. `.github/workflows/release.yml` checks the tag is on `main`, equals that version and is a valid bump, runs every gate (format, lints, tests),
   builds `playlist_bridge-X.Y.Z-py3-none-any.whl` and publishes the release. The notes are the changelog only, generated from the `feat` / `fix` / `perf` /
   `refactor` commits since the previous release (`tools/New-ReleaseNotes.ps1`).

`.github/workflows/ci.yml` runs on every push and pull request: `tools/Test-VersionPolicy.ps1`, the Python format (`ruff format`), lint (`ruff check`) and test (`pytest`) gates, and a build
of the wheel.

Commit titles follow Conventional Commits (`feat:`, `fix:`, `perf:`, `refactor:`, `chore:`, `docs:`, `test:`, `ci:`), because the changelog is
derived from them.

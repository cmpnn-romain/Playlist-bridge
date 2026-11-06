# Playlist-bridge

A small command-line tool that syncs playlists between YouTube Music and Tidal, both ways, additive only. Same repository layout, versioning
and release system as Unplug (`~/Unplug`, <https://github.com/cmpnn-romain/Unplug>).

## Layout

| Path | What it is |
| --- | --- |
| `python/playlist_bridge/matching.py` | the track model and the rules: normalization, soft and hard version tags, scoring, `best_match`, `Index` (is it already in the playlist) |
| `python/playlist_bridge/guard.py` | every request goes through `Guard.call`: pacing with jitter, the daily budget, backoff on 429 / 5xx / network errors, the circuit breaker and its stored cooldown |
| `python/playlist_bridge/db.py` | SQLite state: `matches`, `synced` (the journal), `playlists`, `usage`, `cooldown`, `runs` |
| `python/playlist_bridge/services.py` | `Service` protocol; the ytmusicapi and tidalapi adapters and the two logins |
| `python/playlist_bridge/sync.py` | the sync: pairs playlists by name, resolves tracks, adds in batches of 50, records each batch |
| `python/playlist_bridge/cli.py` | `login`, `sync`, `status`, `reset-cooldown`; the run lock; exit codes (2 = stopped early) |
| `python/tests/` | the tests; fake services only, no network |
| `tools/` | `Build-Release.ps1`, `Test-VersionPolicy.ps1`, `New-ReleaseNotes.ps1` |

## Build and test

```bash
cd python && python -m pip install -e ".[dev]" && ruff format --check . && ruff check . && pytest
```

`python -m build --wheel` (in `python/`) builds the wheel. The tests never touch the real services; a real run needs `login` first.

## Releases and versions

`VERSION` is the single source of truth (strict `MAJOR.MINOR.PATCH`), read by `python/setup.py`. Tag `X.Y.Z` on `main` and push the tag; CI
builds and publishes `playlist_bridge-X.Y.Z-py3-none-any.whl`. Do not upload by hand. Commits follow Conventional Commits; the release notes
are generated from `feat`/`fix`/`perf`/`refactor` titles. See `docs/VERSIONING.md`.

## Pitfalls

- Never delete anything on either service: the sync only adds. Keep it that way.
- Every network call goes through `Guard.call`, so the pacing, the budget and the cooldown always apply. A new call that skips it can get the user's IP blocked.
- Tests must stay offline: use the fakes in `python/tests/test_sync.py`, and inject `sleep` / `clock` into `Guard` so nothing really waits.
- A song is matched on title, artist and duration, since the services share no id. Raising the default threshold loses songs, lowering it adds wrong ones.
- `setuptools` cannot read files outside `python/` (so `readme` and `license-files` are not set in `pyproject.toml`); `setup.py` reads `../VERSION` itself.
- The credentials files are mode 600; never log or print their contents.
- Text files are LF; no BOM.

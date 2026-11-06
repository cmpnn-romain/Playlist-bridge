# Playlist-bridge

A small command-line tool that keeps a YouTube Music and a Tidal library in step (liked songs and playlists), both ways, additive only,
and runs for ever. Same repository layout, versioning
and release system as Unplug (`~/Unplug`, <https://github.com/cmpnn-romain/Unplug>).

## Layout

| Path | What it is |
| --- | --- |
| `python/playlist_bridge/matching.py` | the track model and the rules: normalization, soft and hard version tags, scoring, `best_match`, `Index` (is it already in the playlist) |
| `python/playlist_bridge/guard.py` | every request goes through `Guard.call`: pacing with jitter, the daily budget, backoff on 429 / 5xx / network errors, the circuit breaker and its stored cooldown |
| `python/playlist_bridge/db.py` | SQLite state: `matches`, `synced` (the journal), `playlists`, `usage`, `cooldown` |
| `python/playlist_bridge/services.py` | `Service` protocol; the ytmusicapi and tidalapi adapters |
| `python/playlist_bridge/login.py` | `login`: numbered steps, a hidden paste that ends by itself (`read_pasted`), a check that the headers really log in, the Tidal link |
| `python/playlist_bridge/sync.py` | `sync_once`, one pass: the liked songs (the `LIKED` pseudo-playlist), then the playlists paired by name; resolves tracks, adds in batches of 50, records each batch |
| `python/playlist_bridge/daemon.py` | `run_forever`: a pass, then a long random wait; waits for the next UTC day after a quota stop and for the cooldown after a block; retries a crashed pass with a growing delay |
| `python/playlist_bridge/autostart.py` | `install` / `stop` / `remove`: a systemd user service running `sync`; never restarted after exit code 3 |
| `python/playlist_bridge/update.py` | `update`: shallow-clones `main` to a temp folder, pip-installs it over the current install (twice: `--no-deps --force-reinstall`, then for new dependencies), records the commit in `installed-commit`, restarts the background service on the new code, or stops a sync left running in a terminal (the pid is in the lock file) |
| `python/playlist_bridge/uninstall.py` | `uninstall`: confirms, removes the service, deletes only the files in `files.OWN_FILES`, then removes the program itself (pipx or pip) |
| `python/playlist_bridge/files.py` | the names of the files kept in `~/.config/playlist-bridge`, the run lock (it holds the pid), and `stop_running` (used by `--update`, `--install`, `--uninstall` to stop a sync left in a terminal) |
| `python/playlist_bridge/cli.py` | the actions as flags: `--login`, `--sync` (for ever, or with `--once`), `--install`, `--stop`, `--update`, `--uninstall`, `--reset-cooldown` (the old bare words still work, for existing service files); the run lock; exit codes (0 ok, 1 failed, 2 stopped early, 3 login needed) |
| `python/tests/` | the tests; fake services only, no network |
| `tools/` | `Build-Release.ps1`, `Test-VersionPolicy.ps1`, `New-ReleaseNotes.ps1` |

## Build and test

```bash
cd python && python -m pip install -e ".[dev]" && ruff format --check . && ruff check . && pytest
```

`python -m build --wheel` (in `python/`) builds the wheel. The tests never touch the real services; a real run needs `login` first.

## Releases and versions

The `VERSION` file and the `version` in `python/pyproject.toml` hold the release number (strict `MAJOR.MINOR.PATCH`) and must match: change both together. Tag `X.Y.Z` on `main` and push the tag; CI
builds and publishes `playlist_bridge-X.Y.Z-py3-none-any.whl`. Do not upload by hand. Commits follow Conventional Commits; the release notes
are generated from `feat`/`fix`/`perf`/`refactor` titles. See `docs/VERSIONING.md`.

## Pitfalls

- Never delete anything on either service: the sync only adds. Keep it that way.
- The loop must stay slow: the interval has a floor (`MIN_INTERVAL_HOURS`) and is randomised, and a failed pass backs off. Never add a tight retry loop.
- The liked songs are a pseudo-playlist (`LIKED` in `services.py`) so they go through the same matching, journal and batches. YouTube Music has no bulk like: one request per song.
- Anything that needs the user to log in again must exit with code 3 (`services.need_login`, `EXIT_LOGIN`): the systemd unit does not restart on it, so it cannot retry against the network for ever.
- ytmusicapi only understands `Header: value` lines, so `login.curl_to_headers` turns a pasted "Copy as cURL" (the option people pick first, and the one the steps name) into those lines, including bash's `$'...'` quoting. Keep the steps in step with what the browsers offer. The pasted text holds cookies: never echo, log or print it.
- `update` follows `main` (there are no releases yet), never installs over a checkout, and must leave the current install untouched when anything fails; it never waits for a password (`GIT_TERMINAL_PROMPT=0`). `PLAYLIST_BRIDGE_REPO` overrides the address (private forks, SSH).
- `uninstall` deletes files by name from `files.OWN_FILES`, never the folder: `PLAYLIST_BRIDGE_HOME` can point anywhere. A new file kept there must be added to that list.
- `--sync --force` is refused without `--once`, since it would re-add removed tracks at every pass.
- Every network call goes through `Guard.call`, so the pacing, the budget and the cooldown always apply. A new call that skips it can get the user's IP blocked.
- Tests must stay offline: use the fakes in `python/tests/test_sync.py`, and inject `sleep` / `clock` into `Guard` so nothing really waits.
- A song is matched on title, artist and duration, since the services share no id. Raising the default threshold loses songs, lowering it adds wrong ones.
- `setuptools` cannot read files outside `python/`, so `readme` and `license-files` are not set in `pyproject.toml`.
- The credentials files are mode 600; never log or print their contents.
- Text files are LF; no BOM.

<a name="readme-top"></a>

<br />
<div align="center">
  <h3 align="center">Playlist-bridge</h3>
  <p align="center">Keep your YouTube Music and Tidal playlists the same.</p>
</div>

## Table of Contents

- [About The Project](#about-the-project)
  - [Built With](#built-with)
- [Getting Started](#getting-started)
  - [Prerequisites](#prerequisites)
  - [Installation](#installation)
- [Usage](#usage)
- [How the hard parts are handled](#how-the-hard-parts-are-handled)
- [Credits](#credits)

## About The Project

**Playlist-bridge** is for the music you collected on one service and want on the other. It keeps your YouTube Music and Tidal libraries in step:
the songs you liked, and every playlist, paired by name. It adds to each side what the other one has, and a playlist that exists on only one
side is created on the other. Nothing is ever deleted. It runs for ever, syncing every few hours, slowly enough that neither service has a
reason to block you, and you can stop it and start it again at any time.

Playlist-bridge is an **unofficial**, independent tool. It is not affiliated with YouTube, Google or Tidal. It shares its repository layout,
versioning and release system with [Unplug](https://github.com/cmpnn-romain/Unplug).

### Built With

* [![Python](https://img.shields.io/badge/Python-tool-3776AB?logo=python&logoColor=white)](https://www.python.org/) with [ytmusicapi](https://github.com/sigma67/ytmusicapi) and [tidalapi](https://github.com/EbbLabs/python-tidal)

## Getting Started

### Prerequisites

* Python 3.10 or newer
* A YouTube Music account and a Tidal account

### Installation

Download the latest `playlist_bridge-X.Y.Z-py3-none-any.whl` from the [Releases](https://github.com/cmpnn-romain/Playlist-bridge/releases) page and install it:

```bash
pipx install playlist_bridge-X.Y.Z-py3-none-any.whl   # or: python -m pip install playlist_bridge-X.Y.Z-py3-none-any.whl
playlist-bridge login      # YouTube Music first (paste the request headers copied from music.youtube.com), then Tidal (open the link it prints)
playlist-bridge sync       # then leave it running
```

## Usage

`playlist-bridge sync` does a first pass, then another every 6 hours or so (`--interval-hours`, never less than 1; the wait is random, never
a fixed beat), until you press Ctrl+C. Each pass syncs the liked songs, then every playlist. The first pass over a big library can take longer
than a day's request budget: it stops, waits for the next day and goes on by itself.

```bash
playlist-bridge sync                 # run for ever
playlist-bridge sync --once          # one pass, then exit (for cron)
playlist-bridge status               # request budget, cooldowns, match statistics, recent passes
```

To keep it running in the background on Linux, put this in `~/.config/systemd/user/playlist-bridge.service`, then run
`systemctl --user enable --now playlist-bridge`:

```ini
[Service]
ExecStart=%h/.local/bin/playlist-bridge sync
Restart=on-failure
RestartPreventExitStatus=3

[Install]
WantedBy=default.target
```

- Playlists are paired by name, ignoring case. Songs are only ever added.
- A song with no confident match is reported once and never guessed. `--threshold` (default 0.8) sets how sure it must be;
  `--allow-approx` accepts another recording of the song (live, remix...) when the studio one is missing, and reports it.
- A song you removed (or unliked) after it was synced is not added back. `sync --once --force` ignores that memory.
- A playlist you saved from someone else on YouTube Music cannot be changed; it is reported as an error.
- When a service asks it to slow down, or the daily request budget is used, it waits (see below) and goes on. If a login stops working it
  ends with exit code 3: run `playlist-bridge login` again. `playlist-bridge reset-cooldown ytm` (or `tidal`) ends a pause early.
- Credentials and the database are in `~/.config/playlist-bridge/` (`PLAYLIST_BRIDGE_HOME` changes the folder); the credentials are readable by you only.

## How the hard parts are handled

| Problem | Handling |
|---|---|
| Different titles and formatting | Accents, case, full-width letters, punctuation, `feat.`, "The", `&` / `and`, `Artist - Title` prefixes, and remaster / deluxe / radio-edit / "from the movie" notes are ignored when comparing. |
| Different versions of a song | Remaster, mono, explicit and similar tags are ignored. Live, remix, acoustic, instrumental, cover and karaoke must agree, or the candidate is penalised. Duration (within 3 s) and album break ties. |
| Missing content, regional licensing | A candidate that cannot be played in your region is ignored. A song that is not found is remembered as missing and asked for again only after `--retry-missing-days` (14). |
| Bot detection | One request at a time, one program at a time (a lock file), a random delay between requests with an occasional longer pause, a cache so each song is searched once, and hours-long, random waits between passes. |
| Request quotas | A daily budget per service (`--ytm-quota` 2000, `--tidal-quota` 3000; neither service publishes limits, so these are cautious), kept in the database. |
| HTTP 429, IP blocking | `Retry-After` is honoured, with exponential backoff. After three throttles in a row (or a wait over 15 minutes) a cooldown is stored; the next pass waits until it is over, plus a random delay. A pass that fails (network down...) is retried after 15 min, then 30, 60... up to 4 h. |
| Always on | The loop sleeps in short naps, so Ctrl+C and `systemctl stop` end it within a minute; the progress is saved after every batch. Expired credentials end it with exit code 3 instead of retrying for ever. |
| Idempotency | The playlist's real contents are compared first, then a journal of what was added (written after every batch of 50, so a crash loses nothing), then the match cache. A second run asks for nothing. |

## Credits

See [AUTHORS.md](AUTHORS.md) for the complete list of contributors and the lineage.

## License

Playlist-bridge is free software under the [GNU General Public License v3.0](LICENSE).

<p align="right">(<a href="#readme-top">back to top</a>)</p>

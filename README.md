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

**Playlist-bridge** is for the playlist you built on one service and want on the other. It reads your playlists on YouTube Music and Tidal,
pairs them by name, and adds to each side the songs the other one has. A playlist that exists on only one side is created on the other.
Nothing is ever deleted, and you can stop it and run it again at any time.

Playlist-bridge is an **unofficial**, independent tool. It is not affiliated with YouTube, Google or Tidal. It shares its repository layout,
versioning and release system with [Unplug](https://github.com/cmpnn-romain/Unplug).

### Built With

* [![Python](https://img.shields.io/badge/Python-tool-3776AB?logo=python&logoColor=white)](https://www.python.org/) with [ytmusicapi](https://github.com/sigma67/ytmusicapi) and [tidalapi](https://github.com/tamland/python-tidal)

## Getting Started

### Prerequisites

* Python 3.10 or newer
* A YouTube Music account and a Tidal account

### Installation

Download the latest `playlist_bridge-X.Y.Z-py3-none-any.whl` from the [Releases](https://github.com/cmpnn-romain/Playlist-bridge/releases) page and install it:

```bash
pipx install playlist_bridge-X.Y.Z-py3-none-any.whl   # or: python -m pip install playlist_bridge-X.Y.Z-py3-none-any.whl
playlist-bridge login ytm      # paste the request headers copied from music.youtube.com
playlist-bridge login tidal    # open the link.tidal.com address it prints
```

## Usage

```bash
playlist-bridge sync --dry-run          # search and report, add nothing (it still uses request budget)
playlist-bridge sync                    # do it; safe to interrupt and to run again
playlist-bridge sync -p "Road Trip"     # one playlist
playlist-bridge status --missing        # request budget, cooldowns, match statistics, songs with no match
```

- Playlists are paired by name, ignoring case. Songs are only ever added.
- A song with no confident match is listed at the end and never guessed. `--threshold` (default 0.8) sets how sure it must be;
  `--allow-approx` accepts another recording of the song (live, remix...) when the studio one is missing, and lists it.
- A song you removed after it was synced is not added back, unless you pass `--force`.
- A playlist you saved from someone else on YouTube Music cannot be changed; it is reported under *Errors*.
- When a service asks it to slow down, or the daily request budget is used, it stops cleanly (exit code 2) and the next run resumes.
  `playlist-bridge reset-cooldown ytm` (or `tidal`) ends a pause early.
- Credentials and the database are in `~/.config/playlist-bridge/` (`PLAYLIST_BRIDGE_HOME` changes the folder); the credentials are readable by you only.

## How the hard parts are handled

| Problem | Handling |
|---|---|
| Different titles and formatting | Accents, case, full-width letters, punctuation, `feat.`, "The", `&` / `and`, `Artist - Title` prefixes, and remaster / deluxe / radio-edit / "from the movie" notes are ignored when comparing. |
| Different versions of a song | Remaster, mono, explicit and similar tags are ignored. Live, remix, acoustic, instrumental, cover and karaoke must agree, or the candidate is penalised. Duration (within 3 s) and album break ties. |
| Missing content, regional licensing | A candidate that cannot be played in your region is ignored. A song that is not found is remembered as missing and asked for again only after `--retry-missing-days` (14). |
| Bot detection | One request at a time, one run at a time (a lock file), a random delay between requests with an occasional longer pause, and a cache so each song is searched once. |
| Request quotas | A daily budget per service (`--ytm-quota` 2000, `--tidal-quota` 3000; neither service publishes limits, so these are cautious), kept in the database. |
| HTTP 429, IP blocking | `Retry-After` is honoured, with exponential backoff. After three throttles in a row (or a wait over 15 minutes) a cooldown is stored and later runs leave that service alone until it ends. An expired login says to log in again. |
| Idempotency | The playlist's real contents are compared first, then a journal of what was added (written after every batch of 50, so a crash loses nothing), then the match cache. A second run asks for nothing. |

## Credits

See [AUTHORS.md](AUTHORS.md) for the complete list of contributors and the lineage.

## License

Playlist-bridge is free software under the [GNU General Public License v3.0](LICENSE).

<p align="right">(<a href="#readme-top">back to top</a>)</p>

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
- [Credits](#credits)

## About The Project

**Playlist-bridge** is for the music you collected on one service and want on the other. It keeps your YouTube Music and Tidal libraries in step:
the songs you liked, and every playlist, paired by name. It adds to each side what the other one has, and a playlist that exists on only one
side is created on the other. Nothing is ever deleted. It runs for ever, syncing every few hours, slowly enough that neither service has a
reason to block you, and you can stop it and start it again at any time.

### Built With

* [![Python](https://img.shields.io/badge/Python-tool-3776AB?logo=python&logoColor=white)](https://www.python.org/)

## Getting Started

### Prerequisites

* Python 3.10 or newer, [pipx](https://pipx.pypa.io/) and git
* A YouTube Music account and a Tidal account

### Installation

```bash
git clone git@github.com:cmpnn-romain/Playlist-bridge.git
pipx install ./Playlist-bridge/python
```

To update, from inside the cloned folder: `git pull`, then `pipx install --force ./python`.

## Usage

```bash
playlist-bridge login       # YouTube Music, then Tidal
playlist-bridge sync        # keeps both libraries in step, for ever (Ctrl+C stops it)
playlist-bridge install     # the same, in the background and at every login (Linux, systemd)
playlist-bridge stop        # stops the background sync (`install` turns it on again)
playlist-bridge uninstall   # removes everything: the background sync, your logins and data, and the program itself
```

- Your liked songs and playlists (paired by name) are synced both ways. Songs are only added, never removed, and a song you removed is not added back.
- It syncs every 6 hours or so, slowly and at random times, and waits out any limit or block by itself. If a login stops working, run `playlist-bridge login` again.
- Songs with no confident match are reported once, never guessed.

## Credits

See [AUTHORS.md](AUTHORS.md) for the complete list of contributors and the libraries.

## License

Playlist-bridge is free software under the [GNU General Public License v3.0](LICENSE).

<p align="right">(<a href="#readme-top">back to top</a>)</p>

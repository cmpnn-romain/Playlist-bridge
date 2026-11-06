<a name="readme-top"></a>

<br />
<div align="center">
  <img src="assets/playlist-bridge-icon.png" alt="Playlist-bridge" width="140">
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
pipx install "git+https://github.com/cmpnn-romain/Playlist-bridge.git#subdirectory=python"
```

## Usage

**Log in to YouTube Music, then Tidal**

```bash
playlist-bridge --login
```

**Keep both libraries in step, for ever: in the background and at every login (Linux, systemd)**

```bash
playlist-bridge --sync
```

**The same, in this terminal instead (Ctrl+C stops it)**

```bash
playlist-bridge --sync --foreground
```

**Stop the background sync (`--sync` turns it on again)**

```bash
playlist-bridge --stop
```

**Install the latest version, and restart the background sync**

```bash
playlist-bridge --update
```

**Remove everything: the background sync, your logins and data, and the program itself**

```bash
playlist-bridge --uninstall
```

**Show all the commands and options**

```bash
playlist-bridge --help
```

**Show the installed version**

```bash
playlist-bridge --version
```

## Credits

See [AUTHORS.md](AUTHORS.md) for the complete list of contributors and the libraries.

## License

Playlist-bridge is free software under the [GNU General Public License v3.0](LICENSE).

<p align="right">(<a href="#readme-top">back to top</a>)</p>

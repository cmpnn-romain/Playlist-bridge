# Playlist-bridge Contributors

Playlist-bridge is free software under the GNU General Public License version 3 ([LICENSE](LICENSE)).

## Playlist-bridge

- cmpnn-romain: the tool

## The libraries it talks to

Playlist-bridge reads and writes the two accounts through these libraries. Their code and credits are their authors'; Playlist-bridge only
installs them as dependencies and calls them. Each keeps its own licence.

| Service | Library | Upstream | Licence |
| --- | --- | --- | --- |
| YouTube Music | ytmusicapi | sigma67 and contributors: <https://github.com/sigma67/ytmusicapi> | MIT |
| Tidal | tidalapi (python-tidal) | the python-tidal contributors: <https://github.com/EbbLabs/python-tidal> | LGPL-3.0-or-later |

## Additional libraries and modules

Not part of this repository's own code; each keeps its own license.

| Library | Used for |
| --- | --- |
| requests (through ytmusicapi and tidalapi) | HTTP, and the network errors the request guard recognises |
| rich | The login screen: boxes, colours and the waiting spinner |
| segno | The QR code of the Tidal login link |
| pytest | Tests |
| ruff | Format and lint gates |
| build, setuptools | Building the wheel |

## Whose services they are

YouTube Music, Tidal and the music in them are not ours: they belong to their owners. Playlist-bridge is unofficial and free, and is not
affiliated with or endorsed by Google, YouTube or Tidal.

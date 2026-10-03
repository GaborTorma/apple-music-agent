# Saját, rögzített Python az agentnek

Az agent ezentúl nem a Homebrew Pythonján fut, hanem egy uv-kezelt CPythonon, amely
a telepítési könyvtárban (`~/Agents/Music/.python/`) él, pontos patch-verzióval a
`.python-version`-ből (most 3.14.7). Az `install.sh` és a `deploy.sh` közös
`ensure_venv` függvénye telepíti az uv-t és a Pythont, és csak akkor építi újra a
venv-et, ha az nem a rögzített verzióra mutat.

A Homebrew Python ad-hoc aláírású, az azonosítója a bináris hash-e. Minden
újrafordításnál (patch-frissítés, macOS-frissítés utáni új bottle) a macOS új
alkalmazásnak látta, és elvesztette a Music-hoz adott Automation-engedélyt. A háttérben
futó `sem` session ilyenkor felugró ablak nélkül `-1743`-mal bukott el; ez ismétlődött
minden frissítés után.

A verzió csak tudatos emeléskor változik, és akkor mindkét usernél egyszer újra meg
kell adni az engedélyt. A pinnelt verziónak letölthetőnek kell lennie az uv-n át: a
python-build-standalone lemarad a Homebrew mögött, ezért lett 3.14.7 a 3.14.8 helyett.

Nyitva maradt: az első deploy után mindkét usernél (a `sem`-nél az ő sessionjére
váltva) még egyszer el kell fogadni az engedélyt.

- [`[a199db47]`](https://github.com/GaborTorma/apple-music-agent/commit/a199db477944e7be4cf0e5ce88cdf51f1efeaa1d) · build: pin a uv-managed Python for the agent so the Music Automation grant survives updates

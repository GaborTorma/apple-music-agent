# Telegram → YouTube → Apple Music Agent

## Context

Személyes automatizáció: egy Telegram botnak küldött YouTube link alapján automatikusan letölti a zenét, konvertálja Apple Music-kompatibilis formátumba, hozzáadja az Apple Music könyvtárhoz, megvárja az iCloud Music Library szinkronizációt, majd hozzáadja a "Futás" nevű playlisthez.

Fő use case: hosszú live mixek (akár 2 órás) hozzáadása futáshoz hallgatásra.

## Architektúra

Pipeline architektúra moduláris felépítéssel. Minden lépés külön modul, egy központi orchestrator irányítja a folyamatot.

```
Telegram üzenet (YouTube link)
        │
        ▼
┌─────────────────┐
│  Telegram Bot    │  python-telegram-bot, long polling
│  (bot.py)        │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Orchestrator    │  pipeline vezérlés, státusz callback-ek
│  (pipeline.py)  │
└────────┬────────┘
         │
    ┌────┴────┬──────────┬──────────────┐
    ▼         ▼          ▼              ▼
┌────────┐┌────────┐┌──────────┐┌──────────────┐
│Download││Convert ││Apple     ││Apple Music   │
│(yt-dlp)││(ffmpeg)││Music Add ││Playlist      │
│        ││        ││(JXA/osa) ││(JXA/osa)     │
└────────┘└────────┘└──────────┘└──────────────┘
```

## Modulok

### `bot.py` — Telegram Bot
- `python-telegram-bot` library, long polling mód
- Csak konfigurált user ID-tól fogad üzeneteket
- YouTube link felismerése regex-szel (youtube.com, youtu.be)
- Pipeline indítása async, státusz üzenetek küldése callback-eken keresztül
- Státusz üzenetek:
  1. "Letöltés indítása..."
  2. "Konvertálás m4a-ba..."
  3. "Hozzáadva az Apple Music-hoz, iCloud szinkronizálás..."
  4. "Hozzáadva a Futás playlisthez! [cím - előadó]"
- Hiba esetén: részletes hibaüzenet a lépés megnevezésével

### `pipeline.py` — Orchestrator
- Lépésenként futtatja a modulokat
- Státusz callback rendszer (a bot felé)
- Hibakezelés: ha egy lépés elhasal, cleanup + hibajelentés
- Temp könyvtár kezelés (`tempfile.mkdtemp`), cleanup mindig lefut

### `downloader.py` — YouTube letöltés
- `yt-dlp` subprocess hívás
- Letölti az eredeti audio stream-et (vorbis/opus)
- Metaadatok kinyerése: cím, csatorna név (előadó), thumbnail URL
- Thumbnail letöltése külön fájlba
- Visszatér: audio fájl path, cover path, metaadatok dict

### `converter.py` — Audio konverzió
- Dinamikus bitráta számítás:
  1. `ffprobe` → audio hossz (másodperc)
  2. `target_bitrate = min(192, floor(195_000_000 * 8 / duration_seconds / 1000))` kbps
  3. Ha target < 64 kbps → figyelmeztetés (nagyon hosszú mix)
- `ffmpeg` konverzió → AAC m4a
- Borítókép beágyazása az m4a-ba
- Metaadatok beírása: title, artist tag-ek
- Visszatér: m4a fájl path

### `apple_music.py` — Apple Music integráció
- `osascript` / JXA hívások
- **Fájl hozzáadása:** `add` parancs a Music alkalmazásban
- **iCloud sync polling:**
  - 60 másodpercenként ellenőrzi a `cloud status` property-t
  - Várt értékek: `matched`, `uploaded`, `purchased`
  - Timeout: 20 perc, utána figyelmeztetés (de folytatja a playlist hozzáadást)
- **Playlist kezelés:**
  - Megkeresi a "Futás" nevű playlistet
  - Ha nem létezik → hiba (nem hoz létre automatikusan)
  - Hozzáadja a számot a playlisthez

### `config.py` — Konfiguráció
- Bot token (`.env`-ből)
- Engedélyezett Telegram user ID(k)
- Playlist név (alapértelmezett: "Futás")
- Max bitráta: 192 kbps
- Max fájlméret: 195 MB
- iCloud poll intervallum: 60 mp
- iCloud poll timeout: 20 perc
- Temp könyvtár útvonal

## Projekt struktúra

```
Music/
├── bot.py              # Telegram bot belépési pont
├── pipeline.py         # Orchestrator
├── downloader.py       # yt-dlp wrapper
├── converter.py        # ffmpeg wrapper
├── apple_music.py      # JXA/osascript wrapper
├── config.py           # Konfigurációs értékek
├── .env                # Titkok (bot token, user id)
├── .env.example        # Példa .env
├── requirements.txt    # Python függőségek
└── docs/
```

## Függőségek

**Python csomagok:**
- `python-telegram-bot` — Telegram Bot API
- `python-dotenv` — .env fájl kezelés

**Rendszer eszközök (kell a gépre):**
- `yt-dlp` — YouTube letöltés
- `ffmpeg` + `ffprobe` — audio konverzió, metaadatok

## Hibakezelés

- Minden modul saját exception osztályt dob (`DownloadError`, `ConversionError`, `AppleMusicError`)
- Pipeline elkapja, cleanup-ol, Telegram üzenetet küld a hiba részleteivel
- Temp fájlok mindig törlődnek (try/finally)

## Biztonsági megfontolások

- Bot token `.env` fájlban, nem commitolva
- Csak engedélyezett user ID-któl fogad üzeneteket
- Temp fájlok törlése minden futás után
- Nem hoz létre automatikusan playlistet

## Verifikáció

1. **Unit tesztek:** Minden modul külön tesztelhető mock-okkal
2. **Manuális end-to-end teszt:**
   - Küldj egy YouTube linket a botnak Telegramon
   - Ellenőrizd: letöltés → konverzió → Apple Music-ban megjelenik → iCloud sync → "Futás" playlistben megjelenik
3. **Edge case tesztek:**
   - Nagyon hosszú mix (2+ óra) — bitráta dinamikusan csökken
   - Érvénytelen YouTube link — hibaüzenet
   - Nem létező playlist — hibaüzenet
   - Hálózati hiba letöltés közben — cleanup + hibaüzenet

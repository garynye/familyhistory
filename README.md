# Family History

A preservation-focused static site for the Nye and Mortensen family history
originally published on Homestead.

The public site is intended for GitHub Pages at
`https://familyhistory.garynye.com`.

## Source collections

- `https://nojd.homestead.com`
- `https://karlaugust.homestead.com`
- `https://mortensen.homestead.com`

## Build

The site has no third-party runtime dependencies. Python 3 is used only for
archiving, rendering, and validation.

```sh
python3 scripts/presentation_media.py --check
python3 -m unittest discover -s tests
python3 scripts/archive_homestead.py
python3 scripts/build_site.py
python3 scripts/validate_site.py
python3 -m http.server --directory dist 8000
```

Open `http://localhost:8000`.

## Preservation model

Original HTML responses are stored under `archive/raw/`. Original locally
hosted images and documents are stored under `archive/media/`. The generated
`archive/manifest.json` records the source URL, retrieval time, content type,
byte size, and SHA-256 digest for every captured object.

The public pages are regenerated from those captures. Obsolete Homestead
trackers, forms, guestbooks, and remote scripts are not executed.

Legacy website interface graphics remain in the preservation archive but are
excluded from modern galleries and collection covers. The reviewed exclusions
are recorded in `content/presentation-exclusions.json`; run
`python3 scripts/presentation_media.py` to audit navigation controls, spacers,
tracking pixels, and decorative interface assets found in the source HTML.

## Rights

See [RIGHTS.md](RIGHTS.md). The software license does not grant rights to
archived family material.

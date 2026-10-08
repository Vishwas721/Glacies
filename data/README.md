# data/

Everything in this directory except this README is **gitignored**. It is rebuilt from raw
sources by the ingestion pipeline (Phase 1).

```
data/
├── raw/<city>/<dataset>/<snapshot>/     immutable archive (never edited)
│   ├── data/                            the files exactly as downloaded
│   └── manifest.json                    DatasetManifest: source, licence, per-file sha256
├── interim/<city>/                      clipped / reprojected / validated intermediates
└── processed/<city>/                    canonical datasets consumed by the engine
    └── results/<cache-key>/             one scenario run: transit/, tt_matrix/, accessibility/,
                                         run.json (`glacies scenario run`; a cache, deleted by
                                         `build-city --clean` like everything else here)
```

## Rebuilding everything

```bash
uv run glacies build-city bengaluru --clean   # verify raw → validate → transit → walk → zones
```

`processed/<city>/BUILD.json` records every raw snapshot used (with checksums), the code version
and git commit, the `city.toml` hash, validation results and the manifest hash of each stage.
Two clean builds from the same inputs and code are byte-identical.

## Getting data into the archive

```bash
uv run glacies ingest list                       # sources from city.toml + archived snapshots
uv run glacies ingest register <dataset> <path> --snapshot <name>   # manual downloads (moves)
uv run glacies ingest register ... --copy        # keep the original where it is
uv run glacies ingest fetch <dataset>            # sources with a download_url
uv run glacies ingest verify                     # re-hash everything against manifests
```

Rules:

1. `raw/` is append-only. New content goes into a new snapshot; identical content is detected by
   checksum and not archived twice; reusing a snapshot name for different content is refused.
   **Never replace a file inside a snapshot folder by hand.** Put a new download anywhere else and
   `register` it with a new snapshot name; `verify` reports any snapshot whose files changed.
2. Pick snapshot names that identify the upstream version: the GTFS `feed_version`, the release
   (`2021-R2025A`), or the download date (`2026-10-04`).
3. The engine never reads `raw/` directly, only `processed/`.
4. Back up `raw/` somewhere outside the repo (external drive / cloud folder). The BMTC feed
   may disappear upstream; your archive may become the only copy.

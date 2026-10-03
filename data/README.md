# data/

Everything in this directory except this README is **gitignored**. It is rebuilt from raw
sources by the ingestion pipeline (Phase 1).

```
data/
├── raw/<city>/<dataset>/<download-date>/   immutable downloads + manifest.json (never edited)
├── interim/<city>/                          clipped / reprojected / validated intermediates
└── processed/<city>/                        canonical datasets consumed by the engine
    └── results/<simulation-id>/             Parquet outputs of simulations
```

Rules:

1. `raw/` is append-only. A new download goes into a new dated folder with its own
   `manifest.json` (see `glacies.provenance.DatasetManifest`).
2. The engine never reads `raw/` directly — only `processed/`.
3. Back up `raw/` somewhere outside the repo (external drive / cloud folder). The BMTC feed
   may disappear upstream; your archive may become the only copy.

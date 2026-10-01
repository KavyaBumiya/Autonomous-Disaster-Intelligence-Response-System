"""Offline dataset tooling for AEGIS trained models.

Nothing in this package is imported by the running service. It builds the
labelled datasets and fitted artifacts that `app.ml` loads at request time.

    python -m ml.flood_dataset      # rebuild data/flood_dataset.csv
    python -m ml.train_flood_model  # refit -> app/ml/artifacts/flood_lr_v1.json

Ground truth is GDACS flood events (EC JRC, public domain). Rainfall features
are ERA5 reanalysis from Open-Meteo. Both are keyless, so the dataset rebuilds
on any machine without credentials.
"""
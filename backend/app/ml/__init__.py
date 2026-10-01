"""Trained models served by AEGIS.

Artifacts are JSON documents under `app/ml/artifacts/`, fitted offline by the
code in `backend/ml/`. They are read at request time with no ML runtime
dependency: scoring one logistic model is a dot product and a sigmoid, so
pulling in scikit-learn or torch for it would cost image size and start-up time
for nothing.
"""

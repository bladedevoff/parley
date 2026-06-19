"""A tiny, real, deterministic logistic regression — no fake accuracy formula.

train_in_place uses this to actually FIT weights by gradient descent over a
one-hot cohort feature matrix and report a genuine held-out accuracy. It is
seeded and dependency-free (pure Python), so results are reproducible and
CI-checkable — and, critically, it trains on the owner's cohort structure WITHOUT
exporting any rows: only the learned weights + accuracy leave.

Pure: stdlib (math) only, no band import, no numpy.
"""

from __future__ import annotations

import hashlib
import math
import re


def _seeded_unit(seed: str) -> float:
    h = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return (int(h[:8], 16) / 0xFFFFFFFF) * 2 - 1  # in (-1, 1)


def _sigmoid(z: float) -> float:
    if z < -60:
        return 0.0
    if z > 60:
        return 1.0
    return 1.0 / (1.0 + math.exp(-z))


def _featurize(cohort_key: str) -> list[float]:
    """Turn a cohort label like 'age:25-34|region:west' into GENERALIZING features
    shared across cohorts (age-band midpoint, normalized; region one-hot-ish), so a
    model learns a feature->label relationship rather than memorizing a per-cohort
    lookup. Falls back gracefully for arbitrary labels."""
    age_mid, region_w, region_e = 0.5, 0.0, 0.0
    for part in cohort_key.lower().split("|"):
        if part.startswith("age:"):
            nums = [int(x) for x in re.findall(r"\d+", part)]
            if nums:
                age_mid = (sum(nums) / len(nums)) / 80.0  # normalize ~[0,1]
        elif part.startswith("region:"):
            region_w = 1.0 if "west" in part else 0.0
            region_e = 1.0 if "east" in part else 0.0
    return [age_mid, region_w, region_e]


# NOTE (honest scope): labels below are SYNTHETIC — a noisy linear function of the
# shared features — so train_logreg demonstrates a genuine gradient-descent fit and
# a real held-out accuracy, NOT a production-grade predictor of real outcomes. The
# point Parley proves is "the model is trained in place and no rows leave", not SOTA ML.
def _build_dataset(cohorts: dict) -> tuple[list[list[float]], list[int]]:
    """Expand cohorts into a SHARED-feature matrix with a label that is a real
    (noisy) function of those features — so accuracy reflects genuine learning,
    not a one-hot lookup. Younger cohorts are likelier positives; deterministic
    per-row label noise keeps the task non-trivial. No raw customer data exists."""
    X: list[list[float]] = []
    y: list[int] = []
    for k in cohorts:
        feats = _featurize(k)
        age_mid = feats[0]
        base_p = 0.85 - age_mid  # younger -> higher propensity (a real linear signal)
        for r in range(int(cohorts[k])):
            # deterministic per-row noise so labels aren't perfectly separable
            noise = (int(hashlib.sha256(f"{k}:{r}".encode()).hexdigest()[:4], 16) % 100) / 100.0
            y.append(1 if noise < base_p else 0)
            X.append(feats)
    return X, y


def train_logreg(cohorts: dict, *, epochs: int = 40, lr: float = 0.3, seed: str = "parley") -> dict:
    """Fit logistic regression by batch gradient descent; return weights + REAL
    held-out accuracy. Deterministic given the inputs."""
    X, y = _build_dataset(cohorts)
    n, d = len(X), (len(X[0]) if X else 0)
    if n == 0:
        return {"model": "logreg", "features": 0, "trained_on": 0, "val_accuracy": 0.0, "weights_dim": 0}

    # deterministic train/val split: every 4th row to validation.
    train_idx = [i for i in range(n) if i % 4 != 0]
    val_idx = [i for i in range(n) if i % 4 == 0]

    w = [_seeded_unit(f"{seed}:{j}") * 0.01 for j in range(d)]
    b = 0.0
    for _ in range(epochs):
        gw = [0.0] * d
        gb = 0.0
        for i in train_idx:
            xi, yi = X[i], y[i]
            pred = _sigmoid(sum(w[j] * xi[j] for j in range(d)) + b)
            err = pred - yi
            for j in range(d):
                gw[j] += err * xi[j]
            gb += err
        m = max(1, len(train_idx))
        for j in range(d):
            w[j] -= lr * gw[j] / m
        b -= lr * gb / m

    correct = 0
    for i in val_idx:
        xi = X[i]
        pred = 1 if _sigmoid(sum(w[j] * xi[j] for j in range(d)) + b) >= 0.5 else 0
        correct += int(pred == y[i])
    acc = round(correct / max(1, len(val_idx)), 4)

    return {
        "model": "logistic-regression (in-place, gradient descent)",
        "features": d,
        "weights_dim": d,
        "trained_on": len(train_idx),
        "validated_on": len(val_idx),
        "val_accuracy": acc,
        "rows_exported": 0,
    }

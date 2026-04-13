"""TMC Feedback Loop — training data collection + logistic regression model.

Phase 5 of UCD: collects (signals, classification, engagement) tuples into
tmc_training_data, and periodically trains a logistic regression model to
replace the rule-based TMC.

The trained model is loaded via `load_trained_tmc()` and returns a dict
matching the TherapeuticMomentClassifier.classify() return shape.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

MOMENT_CLASSES = ("CRISIS", "BREAKTHROUGH", "HERITAGE", "RECURRENCE",
                  "THRESHOLD", "INTEGRATION", "REST")

SIGNAL_FEATURE_KEYS = [
    "crystal_confidence_mean", "crystal_locked_count",
    "ec_peak", "ec_trend", "cycle_count", "cycle_severity_mean",
    "days_since_last_generation", "engagement_rate_7d",
    "act_position_ordinal",
]


async def record_training_sample(
    db_pool,
    user_id: str,
    input_signals: dict,
    classified_moment: str,
    *,
    actual_engagement: Optional[str] = None,
    generation_id: Optional[str] = None,
    crystal_response_ids: Optional[list[str]] = None,
    model_version: Optional[str] = None,
) -> str:
    """Write a (signals → class → outcome) row for future model training."""
    sample_id = str(uuid.uuid4())
    gen_uuid = uuid.UUID(generation_id) if generation_id else None
    crystal_uuids = [uuid.UUID(c) for c in (crystal_response_ids or [])]
    async with db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO tmc_training_data "
            "(sample_id, user_id, input_signals, classified_moment, "
            "actual_engagement, generation_id, crystal_response_ids, model_version) "
            "VALUES ($1,$2,$3,$4,$5,$6,$7,$8)",
            uuid.UUID(sample_id), user_id,
            json.dumps(input_signals, default=str),
            classified_moment,
            actual_engagement,
            gen_uuid,
            crystal_uuids,
            model_version or "rule_v1",
        )
    return sample_id


def signals_to_feature_vector(signals: dict) -> list[float]:
    """Convert a signals dict to a fixed-length float vector for the model."""
    vec = []
    for key in SIGNAL_FEATURE_KEYS:
        val = signals.get(key, 0.0)
        if isinstance(val, bool):
            val = 1.0 if val else 0.0
        try:
            vec.append(float(val))
        except (TypeError, ValueError):
            vec.append(0.0)
    return vec


async def train_tmc_model(db_pool, min_samples: int = 100) -> Optional[dict]:
    """Train a logistic regression model from accumulated training data.

    Returns model coefficients dict or None if insufficient data.
    Requires scikit-learn (soft dependency).
    """
    try:
        from sklearn.linear_model import LogisticRegression
        from sklearn.preprocessing import LabelEncoder
        import numpy as np
    except ImportError:
        logger.warning("scikit-learn not available — TMC model training skipped")
        return None

    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT input_signals, classified_moment, actual_engagement "
            "FROM tmc_training_data "
            "WHERE actual_engagement IS NOT NULL "
            "ORDER BY created_at DESC LIMIT 5000"
        )

    if len(rows) < min_samples:
        logger.info("TMC trainer: only %d samples (need %d) — skipping", len(rows), min_samples)
        return None

    X, y = [], []
    le = LabelEncoder()
    le.fit(list(MOMENT_CLASSES))

    for row in rows:
        signals = row["input_signals"]
        if isinstance(signals, str):
            signals = json.loads(signals)
        features = signals_to_feature_vector(signals)
        X.append(features)
        y.append(row["classified_moment"])

    X_arr = np.array(X)
    y_arr = le.transform(y)

    model = LogisticRegression(max_iter=500, multi_class="multinomial")
    model.fit(X_arr, y_arr)

    accuracy = model.score(X_arr, y_arr)
    logger.info("TMC model trained: %d samples, accuracy=%.3f", len(rows), accuracy)

    return {
        "model_version": f"lr_v1_{datetime.now(timezone.utc).strftime('%Y%m%d')}",
        "classes": le.classes_.tolist(),
        "coefficients": model.coef_.tolist(),
        "intercept": model.intercept_.tolist(),
        "accuracy": accuracy,
        "n_samples": len(rows),
        "feature_keys": SIGNAL_FEATURE_KEYS,
        "trained_at": datetime.now(timezone.utc).isoformat(),
    }


async def classify_with_model(
    model_data: dict,
    signals: dict,
) -> dict[str, Any]:
    """Classify a moment using the trained logistic regression model."""
    try:
        import numpy as np
    except ImportError:
        return {"moment_class": "REST", "confidence": 0.0, "model": "fallback"}

    features = signals_to_feature_vector(signals)
    coefs = np.array(model_data["coefficients"])
    intercepts = np.array(model_data["intercept"])
    classes = model_data["classes"]

    logits = coefs @ np.array(features) + intercepts
    exp_logits = np.exp(logits - np.max(logits))
    probs = exp_logits / exp_logits.sum()

    best_idx = int(np.argmax(probs))
    return {
        "moment_class": classes[best_idx],
        "confidence": float(probs[best_idx]),
        "all_scores": {c: float(p) for c, p in zip(classes, probs)},
        "model": model_data.get("model_version", "lr_v1"),
    }

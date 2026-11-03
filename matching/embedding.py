"""CPU-only semantic ranking, independent of YOLO/Qwen and team contracts."""
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import re
from time import perf_counter
import numpy as np

MODEL = "sentence-transformers/all-MiniLM-L6-v2"
ROOT = Path(__file__).resolve().parents[1]


def feature_text(features):
    if not isinstance(features, dict):
        raise ValueError("features must be an object")
    parts = []
    for key in ("category", "colors", "shape", "materials", "logos_or_text", "distinctive_features"):
        value = features.get(key)
        if isinstance(value, str) and value.strip() and value not in ("unknown", "other"):
            parts.append(f"{key.replace('_', ' ')}: {value}")
        elif isinstance(value, list):
            values = [v.strip() for v in value if isinstance(v, str) and v.strip()]
            if values:
                parts.append(f"{key.replace('_', ' ')}: {', '.join(values)}")
    status = features.get("sticker_status")
    if status == "absent":
        parts.append("no stickers")
    elif status == "present":
        parts.append("stickers present")
        for sticker in features.get("stickers", []):
            if isinstance(sticker, dict):
                parts.extend(f"sticker {key}: {value}" for key, value in sticker.items()
                             if key in ("shape", "position") and isinstance(value, str) and value.strip())
    return "; ".join(parts)


def read_candidates(report):
    objects = report.get("objects")
    if not isinstance(objects, list):
        raise ValueError("Expected objects[] from result_with_qwen.json")
    candidates, skipped, seen = [], [], set()
    for obj in objects:
        if not isinstance(obj, dict) or not isinstance(obj.get("id"), int):
            raise ValueError("Every candidate needs an integer id")
        if obj["id"] in seen:
            raise ValueError("Duplicate object id")
        seen.add(obj["id"])
        qwen = obj.get("qwen", {})
        if not isinstance(qwen, dict):
            raise ValueError("qwen must be an object")
        if qwen.get("status") != "ok":
            skipped.append({"id": obj["id"], "reason": "qwen_not_ok"})
            continue
        text = feature_text(qwen.get("features"))
        if not text:
            skipped.append({"id": obj["id"], "reason": "no_observed_features"})
            continue
        candidates.append({"id": obj["id"], "text": text, "features": qwen["features"],
                           "crop_path": obj.get("crop_path"), "center_px": obj.get("center_px"),
                           "center_world_mm": obj.get("center_world_mm"),
                           "calibration_valid": obj.get("calibration_valid", False)})
    return candidates, skipped


def normalized(vectors):
    values = np.asarray(vectors, dtype=np.float32)
    if values.ndim != 2 or not np.isfinite(values).all():
        raise ValueError("Invalid embedding matrix")
    norms = np.linalg.norm(values, axis=1, keepdims=True)
    if np.any(norms <= 1e-12):
        raise ValueError("Zero embedding vector")
    return values / norms


class MiniLMRanker:
    def __init__(self, cache_dir=None, threads=2, offline=False):
        started = perf_counter()
        from fastembed import TextEmbedding
        self.cache = Path(cache_dir or ROOT / ".cache/matching").resolve()
        self.cache.mkdir(parents=True, exist_ok=True)
        self.revision = f"{MODEL}|fastembed={version('fastembed')}|text_v1"
        self.model = TextEmbedding(model_name=MODEL, cache_dir=str(self.cache / "model"),
                                   threads=threads, providers=["CPUExecutionProvider"],
                                   local_files_only=offline)
        self.init_seconds = perf_counter()-started
        self.candidates = []
        self.matrix = None

    def prepare(self, candidates):
        started = perf_counter()
        directory = self.cache / "vectors"
        directory.mkdir(exist_ok=True)
        vectors, missing, positions = [], [], []
        for index, item in enumerate(candidates):
            key = hashlib.sha256((self.revision+"\n"+item["text"]).encode()).hexdigest()
            path = directory / f"{key}.npy"
            value = None
            if path.exists():
                try:
                    value = np.load(path, allow_pickle=False)
                    if value.shape != (384,) or not np.isfinite(value).all() or np.linalg.norm(value) < 1e-12:
                        value = None
                except (OSError, ValueError):
                    value = None
            vectors.append(value)
            if value is None:
                missing.append(item["text"])
                positions.append((index,path))
        if missing:
            encoded = normalized(list(self.model.embed(missing)))
            for vector, (index,path) in zip(encoded, positions):
                vectors[index] = vector
                np.save(path, vector, allow_pickle=False)
        self.candidates = candidates
        self.matrix = normalized(vectors) if candidates else None
        return {"candidate_count": len(candidates), "new_embeddings": len(missing),
                "cache_hits": len(candidates)-len(missing), "prepare_seconds": perf_counter()-started}

    def rank(self, query):
        if not isinstance(query, str) or not query.strip():
            raise ValueError("Query must not be empty")
        if re.search(r"[\uac00-\ud7a3\u1100-\u11ff\u3130-\u318f]", query):
            raise ValueError("This model is English-only. Translate/normalize Korean input first; translation is not implemented here.")
        if not self.candidates:
            return [], {"query_embedding_seconds": 0, "similarity_seconds": 0}
        started = perf_counter()
        vector = normalized(list(self.model.embed([query.strip()])))[0]
        embed_seconds = perf_counter()-started
        started = perf_counter()
        scores = np.clip(self.matrix @ vector, -1, 1)
        order = np.argsort(-scores, kind="stable")
        ranking = [{**self.candidates[i], "cosine_similarity": float(scores[i])} for i in order]
        return ranking, {"query_embedding_seconds": embed_seconds,
                         "similarity_seconds": perf_counter()-started}

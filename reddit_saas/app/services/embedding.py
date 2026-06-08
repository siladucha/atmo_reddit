"""Embedding service for semantic similarity operations.

Uses Google Gemini Embedding API (free tier: 1500 req/min) or OpenAI
text-embedding-3-small ($0.02/1M tokens) as fallback.

Primary use cases:
1. Diversity check — reject generated comments too similar to previous ones
2. Few-shot retrieval — find semantically relevant edit records
3. Semantic pre-filter — match threads to client worldview (future)

Storage: pgvector extension in PostgreSQL (no separate vector DB needed).
"""

import hashlib
from app.logging_config import get_logger
from typing import Optional

import httpx
import numpy as np
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import get_config

logger = get_logger(__name__)

# Embedding dimensions by model
DIMENSIONS = {
    "text-embedding-3-small": 1536,
    "text-embedding-004": 768,  # Gemini
}

# Default model — Gemini is free for our volumes
DEFAULT_MODEL = "text-embedding-004"
DEFAULT_DIMENSIONS = 768


class EmbeddingService:
    """Service for generating and comparing text embeddings."""

    def __init__(self, model: str | None = None):
        self.model = model or DEFAULT_MODEL
        self.dimensions = DIMENSIONS.get(self.model, DEFAULT_DIMENSIONS)

    def embed_text(self, text_input: str, task_type: str = "SEMANTIC_SIMILARITY") -> list[float] | None:
        """Generate embedding for a single text.

        Args:
            text_input: Text to embed (truncated to ~8000 chars internally).
            task_type: Gemini task type (SEMANTIC_SIMILARITY, RETRIEVAL_DOCUMENT, etc.)

        Returns:
            List of floats (embedding vector) or None on failure.
        """
        if not text_input or not text_input.strip():
            return None

        # Truncate to avoid token limits (~2000 tokens ≈ 8000 chars)
        text_input = text_input[:8000]

        try:
            if self.model == "text-embedding-004":
                return self._embed_gemini(text_input, task_type)
            else:
                return self._embed_openai(text_input)
        except Exception as e:
            logger.error(f"Embedding failed for model {self.model}: {e}")
            return None

    def embed_batch(self, texts: list[str], task_type: str = "SEMANTIC_SIMILARITY") -> list[list[float] | None]:
        """Generate embeddings for multiple texts.

        Args:
            texts: List of texts to embed.
            task_type: Gemini task type.

        Returns:
            List of embedding vectors (None for failed items).
        """
        if not texts:
            return []

        # Truncate each
        texts = [t[:8000] for t in texts]

        try:
            if self.model == "text-embedding-004":
                return self._embed_gemini_batch(texts, task_type)
            else:
                return self._embed_openai_batch(texts)
        except Exception as e:
            logger.error(f"Batch embedding failed: {e}")
            # Fallback: try one by one
            return [self.embed_text(t, task_type) for t in texts]

    def cosine_similarity(self, vec_a: list[float], vec_b: list[float]) -> float:
        """Compute cosine similarity between two vectors.

        Returns:
            Float between -1 and 1 (1 = identical, 0 = orthogonal).
        """
        a = np.array(vec_a)
        b = np.array(vec_b)
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(np.dot(a, b) / (norm_a * norm_b))

    def check_diversity(
        self,
        new_text: str,
        previous_texts: list[str],
        threshold: float = 0.85,
    ) -> tuple[bool, float]:
        """Check if new_text is sufficiently different from previous texts.

        Args:
            new_text: The newly generated comment.
            previous_texts: List of previous comments to compare against.
            threshold: Maximum allowed similarity (default 0.85).

        Returns:
            Tuple of (is_diverse: bool, max_similarity: float).
            is_diverse=True means the comment is different enough.
        """
        if not previous_texts:
            return True, 0.0

        new_embedding = self.embed_text(new_text)
        if new_embedding is None:
            # Can't check — allow it through
            logger.warning("Diversity check skipped: embedding failed for new text")
            return True, 0.0

        max_sim = 0.0
        # Only check against last 20 for performance
        check_texts = previous_texts[:20]

        prev_embeddings = self.embed_batch(check_texts)

        for prev_emb in prev_embeddings:
            if prev_emb is None:
                continue
            sim = self.cosine_similarity(new_embedding, prev_emb)
            max_sim = max(max_sim, sim)
            if sim > threshold:
                # Early exit — already too similar
                return False, sim

        return max_sim <= threshold, max_sim

    # --- Private: Gemini API ---

    def _embed_gemini(self, text_input: str, task_type: str) -> list[float] | None:
        """Call Gemini Embedding API."""
        api_key = get_config("gemini_api_key")
        if not api_key:
            logger.error("gemini_api_key not configured")
            return None

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:embedContent"

        payload = {
            "model": f"models/{self.model}",
            "content": {"parts": [{"text": text_input}]},
            "taskType": task_type,
        }

        with httpx.Client(timeout=30) as client:
            resp = client.post(
                url,
                json=payload,
                params={"key": api_key},
            )
            resp.raise_for_status()
            data = resp.json()

        values = data.get("embedding", {}).get("values", [])
        if not values:
            logger.error(f"Gemini returned empty embedding: {data}")
            return None
        return values

    def _embed_gemini_batch(self, texts: list[str], task_type: str) -> list[list[float] | None]:
        """Call Gemini batch embedding API."""
        api_key = get_config("gemini_api_key")
        if not api_key:
            logger.error("gemini_api_key not configured")
            return [None] * len(texts)

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:batchEmbedContents"

        requests_payload = [
            {
                "model": f"models/{self.model}",
                "content": {"parts": [{"text": t}]},
                "taskType": task_type,
            }
            for t in texts
        ]

        with httpx.Client(timeout=60) as client:
            resp = client.post(
                url,
                json={"requests": requests_payload},
                params={"key": api_key},
            )
            resp.raise_for_status()
            data = resp.json()

        embeddings = data.get("embeddings", [])
        results: list[list[float] | None] = []
        for emb in embeddings:
            values = emb.get("values", [])
            results.append(values if values else None)

        # Pad with None if response is shorter than input
        while len(results) < len(texts):
            results.append(None)

        return results

    # --- Private: OpenAI API ---

    def _embed_openai(self, text_input: str) -> list[float] | None:
        """Call OpenAI Embedding API."""
        api_key = get_config("openai_api_key")
        if not api_key:
            logger.error("openai_api_key not configured")
            return None

        url = "https://api.openai.com/v1/embeddings"

        with httpx.Client(timeout=30) as client:
            resp = client.post(
                url,
                json={
                    "model": "text-embedding-3-small",
                    "input": text_input,
                },
                headers={"Authorization": f"Bearer {api_key}"},
            )
            resp.raise_for_status()
            data = resp.json()

        return data["data"][0]["embedding"]

    def _embed_openai_batch(self, texts: list[str]) -> list[list[float] | None]:
        """Call OpenAI batch embedding API."""
        api_key = get_config("openai_api_key")
        if not api_key:
            return [None] * len(texts)

        url = "https://api.openai.com/v1/embeddings"

        with httpx.Client(timeout=60) as client:
            resp = client.post(
                url,
                json={
                    "model": "text-embedding-3-small",
                    "input": texts,
                },
                headers={"Authorization": f"Bearer {api_key}"},
            )
            resp.raise_for_status()
            data = resp.json()

        results: list[list[float] | None] = [None] * len(texts)
        for item in data.get("data", []):
            idx = item.get("index", 0)
            if idx < len(results):
                results[idx] = item.get("embedding")

        return results


# --- Module-level convenience ---

_service: Optional[EmbeddingService] = None


def get_embedding_service() -> EmbeddingService:
    """Get or create the singleton EmbeddingService."""
    global _service
    if _service is None:
        _service = EmbeddingService()
    return _service


def check_comment_diversity(
    new_comment: str,
    previous_comments: list[str],
    threshold: float = 0.85,
) -> tuple[bool, float]:
    """Convenience function: check if a new comment is diverse enough.

    Returns:
        (is_diverse, max_similarity) — is_diverse=True means OK to use.
    """
    service = get_embedding_service()
    return service.check_diversity(new_comment, previous_comments, threshold)


def ensure_pgvector_extension(db: Session) -> None:
    """Create pgvector extension if not exists. Call once on startup."""
    try:
        db.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        db.commit()
        logger.info("pgvector extension ensured")
    except Exception as e:
        db.rollback()
        logger.warning(f"Could not create pgvector extension: {e}")

"""Tests for the embedding service — diversity check and cosine similarity."""

import pytest
from unittest.mock import patch, MagicMock
import numpy as np


class TestCosineSimlarity:
    """Test cosine similarity computation (no API calls needed)."""

    def setup_method(self):
        from app.services.embedding import EmbeddingService
        self.service = EmbeddingService()

    def test_identical_vectors(self):
        vec = [1.0, 0.0, 0.0, 1.0]
        assert self.service.cosine_similarity(vec, vec) == pytest.approx(1.0)

    def test_orthogonal_vectors(self):
        a = [1.0, 0.0, 0.0]
        b = [0.0, 1.0, 0.0]
        assert self.service.cosine_similarity(a, b) == pytest.approx(0.0)

    def test_opposite_vectors(self):
        a = [1.0, 0.0]
        b = [-1.0, 0.0]
        assert self.service.cosine_similarity(a, b) == pytest.approx(-1.0)

    def test_zero_vector(self):
        a = [0.0, 0.0, 0.0]
        b = [1.0, 2.0, 3.0]
        assert self.service.cosine_similarity(a, b) == 0.0

    def test_similar_vectors(self):
        a = [1.0, 2.0, 3.0]
        b = [1.1, 2.1, 3.1]
        sim = self.service.cosine_similarity(a, b)
        assert sim > 0.99  # Very similar

    def test_different_vectors(self):
        a = [1.0, 0.0, 0.0]
        b = [0.0, 0.0, 1.0]
        sim = self.service.cosine_similarity(a, b)
        assert sim == pytest.approx(0.0)


class TestDiversityCheck:
    """Test diversity check logic with mocked embeddings."""

    def setup_method(self):
        from app.services.embedding import EmbeddingService
        self.service = EmbeddingService()

    @patch.object(
        __import__("app.services.embedding", fromlist=["EmbeddingService"]).EmbeddingService,
        "embed_text",
    )
    @patch.object(
        __import__("app.services.embedding", fromlist=["EmbeddingService"]).EmbeddingService,
        "embed_batch",
    )
    def test_diverse_comment_passes(self, mock_batch, mock_text):
        """A comment different from previous ones should pass."""
        # New comment embedding (different direction)
        mock_text.return_value = [1.0, 0.0, 0.0]
        # Previous comments embeddings (all in Y direction)
        mock_batch.return_value = [[0.0, 1.0, 0.0], [0.0, 0.9, 0.1]]

        is_diverse, max_sim = self.service.check_diversity(
            "new comment", ["old1", "old2"], threshold=0.85
        )
        assert is_diverse is True
        assert max_sim < 0.85

    @patch.object(
        __import__("app.services.embedding", fromlist=["EmbeddingService"]).EmbeddingService,
        "embed_text",
    )
    @patch.object(
        __import__("app.services.embedding", fromlist=["EmbeddingService"]).EmbeddingService,
        "embed_batch",
    )
    def test_similar_comment_rejected(self, mock_batch, mock_text):
        """A comment too similar to a previous one should be rejected."""
        # Same direction = high similarity
        mock_text.return_value = [1.0, 0.0, 0.0]
        mock_batch.return_value = [[0.99, 0.01, 0.0]]

        is_diverse, max_sim = self.service.check_diversity(
            "almost same comment", ["very similar"], threshold=0.85
        )
        assert is_diverse is False
        assert max_sim > 0.85

    def test_empty_previous_always_passes(self):
        """No previous comments = always diverse."""
        is_diverse, max_sim = self.service.check_diversity(
            "any comment", [], threshold=0.85
        )
        assert is_diverse is True
        assert max_sim == 0.0

    @patch.object(
        __import__("app.services.embedding", fromlist=["EmbeddingService"]).EmbeddingService,
        "embed_text",
        return_value=None,
    )
    def test_embedding_failure_passes_through(self, mock_text):
        """If embedding fails, allow the comment through (non-critical)."""
        is_diverse, max_sim = self.service.check_diversity(
            "comment", ["prev1", "prev2"], threshold=0.85
        )
        assert is_diverse is True  # Fail-open


class TestCommentOutputSchema:
    """Test that perspective_push is properly validated."""

    def test_valid_perspective_push_values(self):
        from app.schemas.llm_outputs import CommentOutput

        for push in ["hard", "medium", "low", "undetected"]:
            co = CommentOutput(
                comment="test",
                comment_to="post",
                location_depth=0,
                location_reasoning="test",
                comment_approach="reframe_drop",
                strategic_angle="reframe",
                perspective_push=push,
            )
            assert co.perspective_push == push

    def test_default_perspective_push(self):
        from app.schemas.llm_outputs import CommentOutput

        co = CommentOutput(
            comment="test",
            comment_to="post",
            location_depth=0,
            location_reasoning="test",
            comment_approach="reframe_drop",
            strategic_angle="reframe",
        )
        assert co.perspective_push == "undetected"


class TestPromptContent:
    """Test that the generation prompt contains required sections."""

    def test_forbidden_patterns_in_prompt(self):
        with open("app/services/generation.py", "r") as f:
            content = f.read()

        assert "FORBIDDEN PATTERNS" in content
        assert "Em-dashes" in content
        assert "Banned sentence starters" in content
        assert "NEVER start with" in content

    def test_diversity_enforcement_in_prompt(self):
        with open("app/services/generation.py", "r") as f:
            content = f.read()

        assert "DIVERSITY ENFORCEMENT" in content
        assert "Opener scan" in content
        assert "Approach scan" in content
        assert "Vocabulary scan" in content
        assert "Structure scan" in content

    def test_perspective_push_in_output_schema(self):
        with open("app/services/generation.py", "r") as f:
            content = f.read()

        assert '"perspective_push"' in content
        assert "hard | medium | low | undetected" in content

    def test_previous_comments_placeholder(self):
        with open("app/services/generation.py", "r") as f:
            content = f.read()

        assert "{previous_comments}" in content
        assert "run diversity checks above" in content


class TestPipelinePrevComments:
    """Test that the pipeline fetches previous comments per avatar."""

    def test_pipeline_has_per_avatar_cache(self):
        """Verify the pipeline code uses avatar-level caching."""
        with open("app/tasks/ai_pipeline.py", "r") as f:
            content = f.read()

        assert "_avatar_prev_cache" in content
        assert "_get_prev_comments_for_avatar" in content
        assert "CommentDraft.avatar_id ==" in content

    def test_pipeline_has_diversity_check(self):
        """Verify the pipeline integrates embedding diversity check."""
        with open("app/tasks/ai_pipeline.py", "r") as f:
            content = f.read()

        assert "check_comment_diversity" in content
        assert "Diversity check FAILED" in content
        assert "threshold=0.85" in content

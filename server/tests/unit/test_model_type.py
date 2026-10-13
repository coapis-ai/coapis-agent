# -*- coding: utf-8 -*-
"""Model type inference unit tests."""

import pytest

from coapis.providers.model_type import (
    VALID_MODEL_TYPES,
    infer_model_type,
    is_valid_model_type,
)


class TestInferModelType:
    """Tests for infer_model_type()"""

    @pytest.mark.parametrize(
        "model_id,expected",
        [
            ("qwen2.5:7b", "chat"),
            ("gpt-4o", "chat"),
            ("llama3:8b", "chat"),
            ("mistral:7b-instruct", "chat"),
            ("qwen3:8b", "chat"),
            ("gpt-4o-mini", "chat"),  # 'omini' must not match 'omni'
            ("phi-mini", "chat"),
            ("", "chat"),
        ],
    )
    def test_chat(self, model_id, expected):
        assert infer_model_type(model_id) == expected

    @pytest.mark.parametrize(
        "model_id,expected",
        [
            ("qwen3-embedding:0.6b", "embedding"),
            ("text-embedding-3-small", "embedding"),
            ("bge-large-zh", "embedding"),
            ("intfloat/e5-small", "embedding"),
            ("nomic-embed-text", "embedding"),
        ],
    )
    def test_embedding(self, model_id, expected):
        assert infer_model_type(model_id) == expected

    @pytest.mark.parametrize(
        "model_id,expected",
        [
            ("bge-reranker-v2-m3", "rerank"),
            ("jina-reranker-v2-base-en", "rerank"),
            ("rerank-v1", "rerank"),
        ],
    )
    def test_rerank(self, model_id, expected):
        assert infer_model_type(model_id) == expected

    @pytest.mark.parametrize(
        "model_id,expected",
        [
            ("whisper-large-v3", "audio"),
            ("parakeet-tts", "audio"),
            ("sense-voice-asr", "audio"),
            ("speech-recognizer", "audio"),
        ],
    )
    def test_audio(self, model_id, expected):
        assert infer_model_type(model_id) == expected

    def test_precedence_embedding_over_audio(self):
        # embedding is checked before audio
        assert infer_model_type("speech-embedding") == "embedding"

    @pytest.mark.parametrize(
        "model_id,expected",
        [
            ("qwen2.5-vl", "vision"),
            ("qwen2.5-vl:7b", "vision"),
            ("qwen-vl-chat", "vision"),
            ("internvl", "vision"),
            ("llava-7b", "vision"),
            ("qwen2.5-omni-7b", "vision"),
            ("gemini-2.0-flash-vision", "vision"),
            ("clip-vit-base", "vision"),
        ],
    )
    def test_vision(self, model_id, expected):
        assert infer_model_type(model_id) == expected

    def test_name_also_matched(self):
        """model_name is matched too, not just model_id."""
        assert infer_model_type("model-xyz", "My Reranker") == "rerank"
        assert infer_model_type("model-xyz", "Vision Pro") == "vision"

    def test_case_insensitive(self):
        assert infer_model_type("QWEN3-EMBEDDING:0.6B") == "embedding"

    def test_precedence_rerank_over_embedding(self):
        # A model matching both should resolve deterministically
        assert infer_model_type("bge-reranker") == "rerank"


class TestIsValidModelType:
    """Tests for is_valid_model_type()"""

    def test_valid(self):
        for t in VALID_MODEL_TYPES:
            assert is_valid_model_type(t) is True

    def test_invalid(self):
        for t in ("", None, "CHAT", "Embedding", "multimodal", "123"):
            assert is_valid_model_type(t) is False

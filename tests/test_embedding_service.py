from app.services.embedding_service import (
    EmbeddingService,
)


def test_embedding_dimension():
    service = EmbeddingService()

    embedding = service.embed_text(
        "The system supports resumable uploads."
    )

    assert len(embedding) == 384


def test_embedding_is_numeric():
    service = EmbeddingService()

    embedding = service.embed_text(
        "Semantic search finds related content."
    )

    assert len(embedding) > 0

    assert all(
        isinstance(value, float)
        for value in embedding
    )


def test_batch_embeddings():
    service = EmbeddingService()

    embeddings = service.embed_texts(
        [
            "The system supports file uploads.",
            "The worker processes documents.",
        ]
    )

    assert len(embeddings) == 2

    assert len(embeddings[0]) == 384
    assert len(embeddings[1]) == 384
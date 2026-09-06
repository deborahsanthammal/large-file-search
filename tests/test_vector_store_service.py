from pathlib import Path

from app.services.vector_store_service import (
    COLLECTION_NAME,
    VECTOR_SIZE,
    VectorStoreService,
)


def test_create_collection(tmp_path: Path):
    service = VectorStoreService(
        path=str(
            tmp_path / "qdrant"
        )
    )

    collections = (
        service.client.get_collections()
    )

    collection_names = {
        collection.name
        for collection in collections.collections
    }

    assert COLLECTION_NAME in collection_names


def test_upsert_and_search(tmp_path: Path):
    service = VectorStoreService(
        path=str(
            tmp_path / "qdrant"
        )
    )

    vector = [0.0] * VECTOR_SIZE
    vector[0] = 1.0

    service.upsert_chunk(
        chunk_id="11111111-1111-1111-1111-111111111111",
        embedding=vector,
        file_id="file-1",
        chunk_index=0,
        start_byte=0,
        end_byte=100,
    )

    results = service.search(
        query_vector=vector,
        limit=1,
    )

    assert len(results) == 1

    result = results[0]

    assert result.id == (
        "11111111-1111-1111-1111-111111111111"
    )

    assert result.payload["file_id"] == "file-1"
    assert result.payload["chunk_index"] == 0


def test_upsert_is_idempotent(tmp_path: Path):
    service = VectorStoreService(
        path=str(
            tmp_path / "qdrant"
        )
    )

    vector = [0.0] * VECTOR_SIZE
    vector[0] = 1.0

    chunk_id = (
        "22222222-2222-2222-2222-222222222222"
    )

    service.upsert_chunk(
        chunk_id=chunk_id,
        embedding=vector,
        file_id="file-1",
        chunk_index=0,
        start_byte=0,
        end_byte=100,
    )

    service.upsert_chunk(
        chunk_id=chunk_id,
        embedding=vector,
        file_id="file-1",
        chunk_index=0,
        start_byte=0,
        end_byte=100,
    )

    results = service.search(
        query_vector=vector,
        limit=10,
    )

    matching_results = [
        result
        for result in results
        if result.id == chunk_id
    ]

    assert len(matching_results) == 1
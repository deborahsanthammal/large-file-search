import asyncio

from sqlalchemy import func, select

from app.core.database import AsyncSessionLocal, Base, engine
from app.models.chunk import DocumentChunk
from app.services.chunking_service import TextChunk
from app.workers.processor import (
    generate_chunk_id,
    persist_chunk_batch,
)


def test_generate_chunk_id_is_deterministic():
    file_id = (
        "12345678-1234-1234-1234-123456789abc"
    )

    first_id = generate_chunk_id(
        file_id,
        0,
    )

    second_id = generate_chunk_id(
        file_id,
        0,
    )

    assert first_id == second_id


def test_different_chunks_have_different_ids():
    file_id = (
        "12345678-1234-1234-1234-123456789abc"
    )

    first_id = generate_chunk_id(
        file_id,
        0,
    )

    second_id = generate_chunk_id(
        file_id,
        1,
    )

    assert first_id != second_id


def test_different_files_have_different_ids():
    file_a = (
        "12345678-1234-1234-1234-123456789abc"
    )

    file_b = (
        "87654321-4321-4321-4321-cba987654321"
    )

    first_id = generate_chunk_id(
        file_a,
        0,
    )

    second_id = generate_chunk_id(
        file_b,
        0,
    )

    assert first_id != second_id


def test_persist_chunk_batch_is_idempotent():
    async def run_test():
        file_id = (
            "99999999-9999-9999-9999-999999999999"
        )

        async with engine.begin() as conn:
            await conn.run_sync(
                Base.metadata.create_all
            )

        async with AsyncSessionLocal() as db:
            chunks = [
                DocumentChunk(
                    id=generate_chunk_id(
                        file_id,
                        0,
                    ),
                    file_id=file_id,
                    chunk_index=0,
                    start_byte=0,
                    end_byte=100,
                    text="First chunk",
                ),
                DocumentChunk(
                    id=generate_chunk_id(
                        file_id,
                        1,
                    ),
                    file_id=file_id,
                    chunk_index=1,
                    start_byte=100,
                    end_byte=200,
                    text="Second chunk",
                ),
            ]

            # First persistence.
            await persist_chunk_batch(
                db,
                chunks,
            )

            await db.commit()

            # Second persistence of the exact
            # same chunks.
            await persist_chunk_batch(
                db,
                chunks,
            )

            await db.commit()

            result = await db.execute(
                select(
                    func.count(
                        DocumentChunk.id
                    )
                ).where(
                    DocumentChunk.file_id
                    == file_id
                )
            )

            count = result.scalar_one()

            assert count == 2

    asyncio.run(run_test())
import asyncio
from datetime import datetime, timedelta, timezone
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import select, text
from sqlalchemy.dialects.sqlite import insert

from app.core.database import AsyncSessionLocal
from app.models.chunk import DocumentChunk
from app.models.file import File
from app.models.job import ProcessingJob
from app.services.chunking_service import (
    chunk_text_stream,
    stream_file_lines,
)
from app.services.embedding_service import (
    EmbeddingService,
)
from app.services.vector_store_service import (
    VectorStoreService,
)


CHUNK_BATCH_SIZE = 100

# A worker that has been PROCESSING a job longer than this
# is considered stale and can be retried.
STALE_JOB_TIMEOUT = timedelta(
    minutes=10
)


def generate_chunk_id(
    file_id: str,
    chunk_index: int,
) -> str:
    """
    Generate a deterministic ID for a document chunk.

    The same file_id + chunk_index always produces
    the same UUID.
    """

    return str(
        uuid5(
            NAMESPACE_URL,
            f"{file_id}:{chunk_index}",
        )
    )


async def persist_chunk_batch(
    db,
    chunks: list[DocumentChunk],
) -> None:
    """
    Persist chunks using SQLite's
    INSERT ... ON CONFLICT DO NOTHING.

    This makes chunk persistence idempotent.
    """

    if not chunks:
        return

    values = [
        {
            "id": chunk.id,
            "file_id": chunk.file_id,
            "chunk_index": chunk.chunk_index,
            "start_byte": chunk.start_byte,
            "end_byte": chunk.end_byte,
            "text": chunk.text,
        }
        for chunk in chunks
    ]

    statement = insert(
        DocumentChunk.__table__
    ).values(values)

    statement = statement.on_conflict_do_nothing(
        index_elements=[
            DocumentChunk.id
        ]
    )

    await db.execute(statement)


async def process_chunk_batch(
    db,
    embedding_service: EmbeddingService,
    vector_store: VectorStoreService,
    chunks: list[DocumentChunk],
) -> None:
    """
    Persist chunks and their embeddings as one processing batch.
    """

    if not chunks:
        return

    await persist_chunk_batch(
        db,
        chunks,
    )

    texts = [
        chunk.text
        for chunk in chunks
    ]

    embeddings = embedding_service.embed_texts(
        texts
    )

    vector_points = []

    for chunk, embedding in zip(
        chunks,
        embeddings,
        strict=True,
    ):
        vector_points.append(
            {
                "id": chunk.id,
                "vector": embedding,
                "file_id": chunk.file_id,
                "chunk_index": chunk.chunk_index,
                "start_byte": chunk.start_byte,
                "end_byte": chunk.end_byte,
            }
        )

    vector_store.upsert_chunks(
        vector_points
    )

    await db.commit()


async def recover_stale_jobs() -> None:
    """
    Requeue jobs that were left in PROCESSING because
    the worker crashed or was terminated.

    A job is considered stale when its started_at timestamp
    is older than STALE_JOB_TIMEOUT.
    """

    cutoff = (
        datetime.now(timezone.utc)
        - STALE_JOB_TIMEOUT
    )

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(ProcessingJob).where(
                ProcessingJob.status == "PROCESSING",
                ProcessingJob.started_at.is_not(None),
                ProcessingJob.started_at < cutoff,
            )
        )

        stale_jobs = result.scalars().all()

        if not stale_jobs:
            return

        for job in stale_jobs:
            job.status = "QUEUED"
            job.started_at = None
            job.error_message = None

        await db.commit()

        for job in stale_jobs:
            print(
                f"Requeued stale job: {job.id}"
            )


async def process_job(
    job_id: str,
) -> None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(ProcessingJob).where(
                ProcessingJob.id == job_id
            )
        )

        job = result.scalar_one_or_none()

        if job is None:
            print(
                f"Job not found: {job_id}"
            )
            return

        file_result = await db.execute(
            select(File).where(
                File.id == job.file_id
            )
        )

        file_record = (
            file_result.scalar_one_or_none()
        )

        if file_record is None:
            job.status = "FAILED"
            job.error_message = (
                "File record not found"
            )

            await db.commit()
            return

        try:
            file_record.processing_status = (
                "PROCESSING"
            )

            job.status = "PROCESSING"

            await db.commit()

            embedding_service = (
                EmbeddingService()
            )

            vector_store = (
                VectorStoreService()
            )

            processed_bytes = 0
            chunk_index = 0

            lines = stream_file_lines(
                file_record.storage_path
            )

            chunks = chunk_text_stream(
                lines
            )

            chunk_batch: list[
                DocumentChunk
            ] = []

            for chunk in chunks:
                chunk_id = generate_chunk_id(
                    file_record.id,
                    chunk_index,
                )

                document_chunk = DocumentChunk(
                    id=chunk_id,
                    file_id=file_record.id,
                    chunk_index=chunk_index,
                    start_byte=chunk.start_byte,
                    end_byte=chunk.end_byte,
                    text=chunk.text,
                )

                chunk_batch.append(
                    document_chunk
                )

                chunk_index += 1

                processed_bytes = (
                    chunk.end_byte
                )

                if (
                    len(chunk_batch)
                    >= CHUNK_BATCH_SIZE
                ):
                    await process_chunk_batch(
                        db,
                        embedding_service,
                        vector_store,
                        chunk_batch,
                    )

                    job.processed_bytes = (
                        processed_bytes
                    )

                    job.processed_chunks = (
                        chunk_index
                    )

                    await db.commit()

                    chunk_batch.clear()

            if chunk_batch:
                await process_chunk_batch(
                    db,
                    embedding_service,
                    vector_store,
                    chunk_batch,
                )

                job.processed_bytes = (
                    processed_bytes
                )

                job.processed_chunks = (
                    chunk_index
                )

                await db.commit()

                chunk_batch.clear()

            job.processed_bytes = (
                file_record.size
            )

            job.processed_chunks = (
                chunk_index
            )

            job.status = "COMPLETED"

            job.completed_at = (
                datetime.now(timezone.utc)
            )

            file_record.processing_status = (
                "COMPLETED"
            )

            await db.commit()

            print(
                f"Completed job: {job.id} "
                f"({chunk_index} chunks)"
            )

        except Exception as exc:
            await db.rollback()

            job.status = "FAILED"

            job.error_message = str(exc)

            file_record.processing_status = (
                "FAILED"
            )

            file_record.error_message = (
                str(exc)
            )

            await db.commit()

            print(
                f"Failed job {job.id}: {exc}"
            )


async def get_next_job() -> str | None:
    """
    Atomically claim the oldest QUEUED job.

    SQLite uses BEGIN IMMEDIATE so that two worker
    processes cannot claim the same job at the same time.
    """

    async with AsyncSessionLocal() as db:

        # Acquire a write transaction before selecting
        # the job. This prevents another worker from
        # claiming the same QUEUED job concurrently.
        await db.execute(
            text("BEGIN IMMEDIATE")
        )

        result = await db.execute(
            select(ProcessingJob)
            .where(
                ProcessingJob.status == "QUEUED"
            )
            .order_by(
                ProcessingJob.created_at
            )
            .limit(1)
        )

        job = result.scalar_one_or_none()

        if job is None:
            await db.rollback()
            return None

        job.status = "PROCESSING"

        job.started_at = (
            datetime.now(timezone.utc)
        )

        await db.commit()

        return job.id


async def run_worker() -> None:
    print("Worker started")

    while True:
        # Recover jobs abandoned by a crashed worker.
        await recover_stale_jobs()

        job_id = await get_next_job()

        if job_id is None:
            await asyncio.sleep(2)
            continue

        print(
            f"Processing job: {job_id}"
        )

        await process_job(job_id)


if __name__ == "__main__":
    asyncio.run(run_worker())
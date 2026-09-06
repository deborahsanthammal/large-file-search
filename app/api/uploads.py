import asyncio
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.models.file import File
from app.models.job import ProcessingJob
from app.services.upload_service import UploadService


router = APIRouter(
    prefix="/uploads",
    tags=["uploads"],
)


# One lock per upload ID.
#
# Different uploads can proceed concurrently.
# Chunks for the same upload are serialized.
_upload_locks: dict[str, asyncio.Lock] = {}


def get_upload_lock(
    upload_id: str,
) -> asyncio.Lock:
    """
    Return the lock associated with an upload.

    Locks are created lazily.
    """

    lock = _upload_locks.get(upload_id)

    if lock is None:
        lock = asyncio.Lock()
        _upload_locks[upload_id] = lock

    return lock


class CreateUploadRequest(BaseModel):
    filename: str = Field(
        min_length=1,
        max_length=255,
    )

    size: int = Field(
        gt=0,
    )


class CreateUploadResponse(BaseModel):
    upload_id: str
    filename: str
    size: int
    offset: int
    status: str


@router.get(
    "/{upload_id}",
    response_model=CreateUploadResponse,
)
async def get_upload(
    upload_id: str,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(File).where(
            File.id == upload_id
        )
    )

    file_record = (
        result.scalar_one_or_none()
    )

    if file_record is None:
        raise HTTPException(
            status_code=404,
            detail="Upload not found",
        )

    return CreateUploadResponse(
        upload_id=file_record.id,
        filename=file_record.filename,
        size=file_record.size,
        offset=file_record.upload_offset,
        status=file_record.upload_status,
    )


@router.post(
    "",
    response_model=CreateUploadResponse,
)
async def create_upload(
    request: CreateUploadRequest,
    db: AsyncSession = Depends(get_db),
):
    if request.size > settings.max_file_size:
        raise HTTPException(
            status_code=413,
            detail=(
                "File exceeds the maximum allowed "
                "size of 10 GB"
            ),
        )

    upload_service = UploadService()

    upload_id, file_path = (
        upload_service.create_upload(
            request.filename
        )
    )

    file_record = File(
        id=upload_id,
        filename=request.filename,
        size=request.size,
        upload_offset=0,
        storage_path=str(file_path),
        upload_status="UPLOADING",
        processing_status="PENDING",
    )

    db.add(file_record)

    await db.commit()

    return CreateUploadResponse(
        upload_id=upload_id,
        filename=request.filename,
        size=request.size,
        offset=0,
        status="UPLOADING",
    )


@router.patch(
    "/{upload_id}"
)
async def upload_chunk(
    upload_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    upload_lock = get_upload_lock(
        upload_id
    )

    async with upload_lock:

        result = await db.execute(
            select(File).where(
                File.id == upload_id
            )
        )

        file_record = (
            result.scalar_one_or_none()
        )

        if file_record is None:
            raise HTTPException(
                status_code=404,
                detail="Upload not found",
            )

        if (
            file_record.upload_status
            != "UPLOADING"
        ):
            raise HTTPException(
                status_code=409,
                detail=(
                    "Upload is no longer "
                    "accepting data"
                ),
            )

        content_length = (
            request.headers.get(
                "content-length"
            )
        )

        upload_offset = (
            request.headers.get(
                "upload-offset"
            )
        )

        if content_length is None:
            raise HTTPException(
                status_code=411,
                detail=(
                    "Content-Length header "
                    "is required"
                ),
            )

        if upload_offset is None:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Upload-Offset header "
                    "is required"
                ),
            )

        try:
            chunk_size = int(
                content_length
            )

            client_offset = int(
                upload_offset
            )

        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Content-Length and "
                    "Upload-Offset must be integers"
                ),
            )

        if (
            chunk_size < 0
            or client_offset < 0
        ):
            raise HTTPException(
                status_code=400,
                detail=(
                    "Chunk size and upload "
                    "offset cannot be negative"
                ),
            )

        if (
            client_offset
            != file_record.upload_offset
        ):
            raise HTTPException(
                status_code=409,
                detail={
                    "message": (
                        "Upload offset does not "
                        "match server state"
                    ),
                    "expected_offset": (
                        file_record.upload_offset
                    ),
                },
            )

        if (
            client_offset + chunk_size
            > file_record.size
        ):
            raise HTTPException(
                status_code=413,
                detail=(
                    "Upload exceeds the "
                    "expected file size"
                ),
            )

        file_path = Path(
            file_record.storage_path
        )

        temp_chunk_path = (
            file_path.parent
            / f"{file_path.name}.chunk"
        )

        bytes_received = 0

        try:
            # Receive the request into a temporary
            # chunk file first.
            with temp_chunk_path.open(
                "wb"
            ) as chunk_file:

                async for chunk in (
                    request.stream()
                ):
                    chunk_file.write(chunk)

                    bytes_received += len(
                        chunk
                    )

                    # Stop accepting data if the
                    # request body itself exceeds
                    # the declared Content-Length.
                    if (
                        bytes_received
                        > chunk_size
                    ):
                        raise HTTPException(
                            status_code=400,
                            detail=(
                                "Received more bytes "
                                "than Content-Length"
                            ),
                        )

            # Verify the complete chunk before
            # touching the real upload file.
            if (
                bytes_received
                != chunk_size
            ):
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Expected {chunk_size} bytes, "
                        f"but received "
                        f"{bytes_received} bytes"
                    ),
                )

            # Append the validated chunk to the
            # actual upload.
            with temp_chunk_path.open(
                "rb"
            ) as chunk_file:

                with file_path.open(
                    "ab"
                ) as output_file:

                    while True:
                        data = (
                            chunk_file.read(
                                1024 * 1024
                            )
                        )

                        if not data:
                            break

                        output_file.write(
                            data
                        )

            file_record.upload_offset = (
                client_offset
                + bytes_received
            )

            if (
                file_record.upload_offset
                == file_record.size
            ):
                upload_service = (
                    UploadService()
                )

                final_path = (
                    upload_service
                    .finalize_upload(
                        file_path
                    )
                )

                file_record.storage_path = (
                    str(final_path)
                )

                file_record.upload_status = (
                    "COMPLETED"
                )

                existing_job_result = (
                    await db.execute(
                        select(
                            ProcessingJob
                        ).where(
                            ProcessingJob.file_id
                            == file_record.id
                        )
                    )
                )

                existing_job = (
                    existing_job_result
                    .scalar_one_or_none()
                )

                if existing_job is None:
                    processing_job = (
                        ProcessingJob(
                            id=str(uuid4()),
                            file_id=file_record.id,
                            status="QUEUED",
                            processed_bytes=0,
                            processed_chunks=0,
                        )
                    )

                    db.add(
                        processing_job
                    )

            await db.commit()

        finally:
            # Always remove the temporary chunk,
            # including when validation fails.
            if temp_chunk_path.exists():
                temp_chunk_path.unlink()

        return {
            "upload_id": upload_id,
            "offset": (
                file_record.upload_offset
            ),
            "size": file_record.size,
            "status": (
                file_record.upload_status
            ),
        }
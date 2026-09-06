from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.chunk import DocumentChunk
from app.models.file import File
from app.services.embedding_service import EmbeddingService
from app.services.vector_store_service import VectorStoreService


router = APIRouter(
    prefix="/search",
    tags=["Search"],
)


SIMILARITY_THRESHOLD = 0.30


class SearchRequest(BaseModel):
    query: str = Field(
        min_length=1,
        max_length=1000,
    )

    limit: int = Field(
        default=5,
        ge=1,
        le=20,
    )


class SearchResult(BaseModel):
    file_id: str
    filename: str
    chunk_id: str
    chunk_index: int
    score: float
    start_byte: int
    end_byte: int
    text: str


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResult]


@router.post(
    "",
    response_model=SearchResponse,
)
async def search(
    request: SearchRequest,
    db: AsyncSession = Depends(get_db),
):
    embedding_service = EmbeddingService()

    vector_store = VectorStoreService()

    query_embedding = (
        embedding_service.embed_text(
            request.query
        )
    )

    vector_results = vector_store.search(
        query_vector=query_embedding,
        limit=request.limit,
    )

    vector_results = [
        result
        for result in vector_results
        if float(result.score) >= SIMILARITY_THRESHOLD
    ]

    if not vector_results:
        return SearchResponse(
            query=request.query,
            results=[],
        )

    chunk_ids = [
        str(result.id)
        for result in vector_results
    ]

    chunk_result = await db.execute(
        select(
            DocumentChunk,
            File.filename,
        )
        .join(
            File,
            File.id == DocumentChunk.file_id,
        )
        .where(
            DocumentChunk.id.in_(chunk_ids)
        )
    )

    rows = chunk_result.all()

    chunks_by_id = {
        chunk.id: (chunk, filename)
        for chunk, filename in rows
    }

    results = []

    for vector_result in vector_results:
        chunk_id = str(
            vector_result.id
        )

        chunk_data = chunks_by_id.get(
            chunk_id
        )

        if chunk_data is None:
            continue

        chunk, filename = chunk_data

        results.append(
            SearchResult(
                file_id=chunk.file_id,
                filename=filename,
                chunk_id=chunk.id,
                chunk_index=chunk.chunk_index,
                score=float(
                    vector_result.score
                ),
                start_byte=chunk.start_byte,
                end_byte=chunk.end_byte,
                text=chunk.text,
            )
        )

    return SearchResponse(
        query=request.query,
        results=results,
    )
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams


COLLECTION_NAME = "document_chunks"
VECTOR_SIZE = 384


class VectorStoreService:
    def __init__(
        self,
        path: str = "./data/indexes/qdrant",
    ) -> None:
        self.client = QdrantClient(
            path=path,
        )

        self._ensure_collection()

    def _ensure_collection(self) -> None:
        """
        Create the collection if it does not already exist.
        """

        collections = (
            self.client.get_collections()
        )

        collection_names = {
            collection.name
            for collection in collections.collections
        }

        if COLLECTION_NAME not in collection_names:
            self.client.create_collection(
                collection_name=COLLECTION_NAME,
                vectors_config=VectorParams(
                    size=VECTOR_SIZE,
                    distance=Distance.COSINE,
                ),
            )

    def upsert_chunk(
        self,
        chunk_id: str,
        embedding: list[float],
        file_id: str,
        chunk_index: int,
        start_byte: int,
        end_byte: int,
    ) -> None:
        """
        Store or update a single chunk vector.

        The chunk_id is used as the Qdrant point ID,
        making this operation idempotent.
        """

        point = PointStruct(
            id=chunk_id,
            vector=embedding,
            payload={
                "file_id": file_id,
                "chunk_index": chunk_index,
                "start_byte": start_byte,
                "end_byte": end_byte,
            },
        )

        self.client.upsert(
            collection_name=COLLECTION_NAME,
            points=[point],
        )

    def upsert_chunks(
        self,
        chunks: list[dict],
    ) -> None:
        """
        Store or update multiple chunk vectors in one
        Qdrant operation.

        Each dictionary must contain:

            id
            vector
            file_id
            chunk_index
            start_byte
            end_byte
        """

        if not chunks:
            return

        points = [
            PointStruct(
                id=chunk["id"],
                vector=chunk["vector"],
                payload={
                    "file_id": chunk["file_id"],
                    "chunk_index": chunk[
                        "chunk_index"
                    ],
                    "start_byte": chunk[
                        "start_byte"
                    ],
                    "end_byte": chunk[
                        "end_byte"
                    ],
                },
            )
            for chunk in chunks
        ]

        self.client.upsert(
            collection_name=COLLECTION_NAME,
            points=points,
        )

    def search(
        self,
        query_vector: list[float],
        limit: int = 5,
    ) -> list:
        """
        Search for the most semantically similar chunks.
        """

        return self.client.query_points(
            collection_name=COLLECTION_NAME,
            query=query_vector,
            limit=limit,
        ).points
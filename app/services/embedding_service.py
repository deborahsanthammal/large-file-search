from sentence_transformers import SentenceTransformer


MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"


class EmbeddingService:
    _model: SentenceTransformer | None = None

    def __init__(self) -> None:
        if EmbeddingService._model is None:
            EmbeddingService._model = (
                SentenceTransformer(MODEL_NAME)
            )

        self.model = EmbeddingService._model

    def embed_text(
        self,
        text: str,
    ) -> list[float]:
        """
        Generate a semantic embedding for a single
        piece of text.
        """

        embedding = self.model.encode(
            text,
            normalize_embeddings=True,
        )

        return embedding.tolist()

    def embed_texts(
        self,
        texts: list[str],
    ) -> list[list[float]]:
        """
        Generate semantic embeddings for multiple
        pieces of text in one batch.
        """

        embeddings = self.model.encode(
            texts,
            normalize_embeddings=True,
        )

        return embeddings.tolist()
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.search import router as search_router
from app.api.uploads import router as uploads_router
from app.core.database import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(
    title="Large File Processing & Semantic Search",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(
    uploads_router
)

app.include_router(
    search_router
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
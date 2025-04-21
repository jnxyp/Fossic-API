from contextlib import asynccontextmanager
from typing import AsyncIterator
from fastapi import FastAPI
from fastapi_cache.backends.inmemory import InMemoryBackend
from api import router
from fastapi_cache import FastAPICache
from fastapi_cache.decorator import cache

@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    FastAPICache.init(InMemoryBackend(), prefix="cache")
    yield

app = FastAPI(lifespan=lifespan)

app.include_router(router, prefix="/api", tags=["api"])

@app.get("/")
def read_root():
    return {"message": "Welcome to the Fossic API!"}
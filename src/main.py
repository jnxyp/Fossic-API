from contextlib import asynccontextmanager
from typing import AsyncIterator
from fastapi import FastAPI
from fastapi_cache.backends.inmemory import InMemoryBackend
from api import router
from fastapi_cache import FastAPICache
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from cache import mod_cache
from config import CONFIG
import log

logger = log.setup_custom_logger(__name__)

def refresh_cache():
    logger.info("触发刷新 ModCache")
    mod_cache.refresh()

@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    # fastapi cache
    FastAPICache.init(InMemoryBackend(), prefix="cache")
    # mod cache
    refresh_cache()
    scheduler = BackgroundScheduler()
    scheduler.add_job(refresh_cache, trigger=IntervalTrigger(seconds=CONFIG["cache"]["mod_cache_time"]), id="refresh_cache", replace_existing=True, max_instances=1, coalesce=True)
    scheduler.start()
    yield
    scheduler.shutdown(wait=False)

app = FastAPI(lifespan=lifespan)
app.include_router(router, prefix="/api", tags=["api"])

@app.get("/")
def read_root():
    return {"message": "Fossic API is up and running!"}

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncGenerator
from fastapi import FastAPI
from fastapi_cache.backends.inmemory import InMemoryBackend
from api import router
from fastapi_cache import FastAPICache
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger


from cache import mod_cache
from config import CONFIG
import log

logger = log.setup_custom_logger(__name__)

_loop: asyncio.AbstractEventLoop | None = None

def refresh_cache():
    logger.info("触发刷新 ModCache")
    if mod_cache.refresh() and _loop is not None:
        asyncio.run_coroutine_threadsafe(FastAPICache.clear(), _loop)

@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None, None]:
    global _loop
    _loop = asyncio.get_event_loop()
    # fastapi cache
    FastAPICache.init(InMemoryBackend(), prefix="cache")
    # mod cache — run in thread pool to avoid blocking the event loop
    await asyncio.get_event_loop().run_in_executor(None, refresh_cache)
    scheduler = BackgroundScheduler()
    scheduler.add_job(refresh_cache, trigger=IntervalTrigger(seconds=CONFIG["cache"]["mod_cache_time"]), id="refresh_cache", replace_existing=True, max_instances=1, coalesce=True)
    scheduler.start()
    yield
    scheduler.shutdown(wait=False)

app = FastAPI(lifespan=lifespan)
app.include_router(router, prefix="/api", tags=["api"])
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

@app.get("/")
def read_root():
    return {"message": f"欢迎来到 Fossic API！请访问 {CONFIG['fossic']['api_url']}/docs 查看 API 文档。API路径为 {CONFIG['fossic']['api_url']}/api/"}

import os

# Never use the developer's .env database, even during imports.
for key, value in {'DB_HOST': '127.0.0.1', 'DB_PORT': '1', 'DB_USER': 'test',
                   'DB_PASSWORD': 'test', 'DB_DATABASE': 'test', 'DEBUG': 'false',
                   'PYTHON_DOTENV_DISABLED': '1',
                   'ALLOWED_HOSTS': 'api.fossic.org,localhost,127.0.0.1,testserver'}.items():
    os.environ[key] = value


import pytest


@pytest.fixture(autouse=True)
def isolated_download_stats(tmp_path, monkeypatch):
    # Also replace the import-time singleton: no test may touch a developer/production ledger.
    from config import CONFIG
    from cache import snapshot_cache
    from download_stats import DownloadStatsStore
    path = tmp_path / 'download-stats.sqlite3'
    store = DownloadStatsStore(path)
    store.initialize()
    monkeypatch.setitem(CONFIG['download_stats'], 'db_path', str(path))
    monkeypatch.setattr(snapshot_cache, 'stats_store', store)
    yield store

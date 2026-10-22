import os

# Never use the developer's .env database, even during imports.
for key, value in {'DB_HOST': '127.0.0.1', 'DB_PORT': '1', 'DB_USER': 'test',
                   'DB_PASSWORD': 'test', 'DB_DATABASE': 'test', 'DEBUG': 'false',
                   'PYTHON_DOTENV_DISABLED': '1',
                   'ALLOWED_HOSTS': 'api.fossic.org,localhost,127.0.0.1,testserver'}.items():
    os.environ[key] = value

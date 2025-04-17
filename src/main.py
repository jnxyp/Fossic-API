from fastapi import FastAPI
from api_routes import router

app = FastAPI()

app.include_router(router, prefix="/api", tags=["api"])

@app.get("/")
def read_root():
    return {"message": "Welcome to the Fossic API!"}
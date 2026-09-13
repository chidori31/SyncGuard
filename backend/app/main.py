from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.api import router
from app.core import event
from app.db import engine

app = FastAPI(title="SyncGuard", version="0.3.0")
app.include_router(router)


@app.get("/health")
def health():
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return {"status": "ok", "database": "ready"}
    except SQLAlchemyError:
        return JSONResponse(status_code=503, content={"status": "unavailable", "database": "unavailable"})


@app.exception_handler(Exception)
async def api_error(request, exc):
    event("api_error", method=request.method)
    return JSONResponse(status_code=500, content={"detail": "Internal service error"})

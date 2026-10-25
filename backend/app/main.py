import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import admin, auth, chat, decisions, memories, stream
from app.core.config import settings
from app.db import indexes
from app.services import embeddings, events_service
from app.workers import scheduler

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("teammind")


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        indexes.ensure_all()
    except Exception as e:
        log.error("Could not reach MongoDB / create indexes: %s", e)
    if settings.use_langgraph:
        from app.graph import registry  # compiles every graph once, here at startup
        log.info("LangGraph ready: %s (checkpointer: %s)", ", ".join(registry.GRAPHS), registry.checkpointer_kind)
    threading.Thread(target=embeddings.warmup, daemon=True).start()  # load the model once, at startup
    events_service.start_change_stream()
    scheduler.start()
    yield
    scheduler.stop()


app = FastAPI(title="TeamMind", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in settings.cors_origins.split(",")],
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
for r in (auth, chat, decisions, memories, stream, admin):
    app.include_router(r.router)


@app.exception_handler(HTTPException)
async def http_err(_: Request, e: HTTPException):
    return JSONResponse({"error": e.detail, "detail": e.detail}, status_code=e.status_code)


@app.exception_handler(RequestValidationError)
async def val_err(_: Request, e: RequestValidationError):
    msg = "; ".join(f"{'.'.join(str(x) for x in er['loc'][1:])}: {er['msg']}" for er in e.errors())
    return JSONResponse({"error": msg}, status_code=422)


@app.exception_handler(Exception)
async def any_err(_: Request, e: Exception):
    log.exception("Unhandled error")
    return JSONResponse({"error": "Something went wrong on the server"}, status_code=500)


@app.get("/")
def root():
    return {"app": "TeamMind", "docs": "/docs"}

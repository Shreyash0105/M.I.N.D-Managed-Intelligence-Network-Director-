import json
from queue import Empty

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.core.security import ctx
from app.services.events_service import broadcaster

router = APIRouter()


@router.get("/stream/memories")
def stream(c=Depends(ctx)):
    q = broadcaster.subscribe(c.ws_id, c.uid)

    def gen():
        try:
            yield f"data: {json.dumps({'kind': 'hello', 'mode': broadcaster.mode})}\n\n"
            while True:
                try:
                    yield f"data: {json.dumps(q.get(timeout=15), default=str)}\n\n"
                except Empty:
                    yield ": ping\n\n"  # keeps proxies from closing the connection
        finally:
            broadcaster.unsubscribe(c.ws_id, q)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

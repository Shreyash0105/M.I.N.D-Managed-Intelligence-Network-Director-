import logging
from apscheduler.schedulers.background import BackgroundScheduler
from app.agents import freshness, reflection
from app.core.config import settings
from app.core.util import utcnow
from app.db.mongo import db

log = logging.getLogger("teammind.jobs")
sched = BackgroundScheduler()


def _runner(name: str):
    if settings.use_langgraph:
        from app.graph import runners
        return {"freshness": runners.run_freshness, "reflection": runners.run_reflection}[name]
    return {"freshness": freshness.run, "reflection": reflection.run}[name]


def run_job(name: str, **kw) -> dict:
    """Runs the Freshness or Reflection graph (or the plain functions when USE_LANGGRAPH=false) and logs the job."""
    t0 = utcnow()
    try:
        res = _runner(name)(**kw)
    except Exception as e:
        db.jobs.update_one({"_id": name}, {"$set": {"last_run": t0, "last_error": str(e)[:300]}}, upsert=True)
        raise
    db.jobs.update_one({"_id": name}, {"$set": {"last_run": t0, "finished_at": utcnow(), "last_result": res, "last_error": None}},
                       upsert=True)
    return res


def _all_reflection():
    for w in db.workspaces.find({}, {"_id": 1}):
        try:
            run_job("reflection", ws=str(w["_id"]))
        except Exception:
            log.exception("reflection failed")


def _freshness():
    try:
        run_job("freshness")
    except Exception:
        log.exception("freshness failed")


def start():
    sched.add_job(_freshness, "interval", hours=1, id="freshness", replace_existing=True)
    sched.add_job(_all_reflection, "cron", hour=3, id="reflection", replace_existing=True)
    sched.start()


def stop():
    if sched.running:
        sched.shutdown(wait=False)

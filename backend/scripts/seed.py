"""python -m scripts.seed  -> creates alex@demo.com / priya@demo.com (password demo1234), one shared workspace, ~13 memories."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.util import utcnow
from app.db import indexes
from app.db.mongo import db
from app.services import seed

if __name__ == "__main__":
    indexes.ensure_all()
    alex, priya = seed.create_demo_users()
    ws = db.workspaces.find_one({"name": "Hackathon Demo"})
    if not ws:
        r = db.workspaces.insert_one({
            "name": "Hackathon Demo", "owner_id": str(alex["_id"]),
            "members": [{"user_id": str(alex["_id"]), "role": "owner"}, {"user_id": str(priya["_id"]), "role": "member"}],
            "settings": {"retention_days": 365, "privacy_mode": "standard"}, "created_at": utcnow()})
        ws_id = str(r.inserted_id)
    else:
        ws_id = str(ws["_id"])
    print(seed.seed_workspace(ws_id, str(alex["_id"])))
    print(f"Login as alex@demo.com / {seed.DEMO_PASSWORD}  (and priya@demo.com in a second window)")

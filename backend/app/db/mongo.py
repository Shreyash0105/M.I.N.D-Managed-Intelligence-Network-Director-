from pymongo import MongoClient
from app.core.config import settings

# tz_aware=True so every datetime we read back is timezone-aware (UTC)
client = MongoClient(settings.mongodb_uri, serverSelectionTimeoutMS=8000, tz_aware=True)
db = client[settings.mongodb_db]

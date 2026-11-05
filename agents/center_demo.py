"""Run: python -m uvicorn agents.center_demo:app --host 127.0.0.1 --port 8110 --no-proxy-headers."""
from pathlib import Path
from agents.center_api import create_app
from center.demo_collections import DemoCollections

# No DATABASE_URL, staff credential, webhook or existing team fixture is used.
app = create_app(collections=DemoCollections(
    Path(__file__).resolve().parents[1] / '.cache/center-collection-demo.sqlite3'), demo=True)

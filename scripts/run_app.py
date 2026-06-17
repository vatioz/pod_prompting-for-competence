from __future__ import annotations

import sys
from pathlib import Path

from waitress import serve

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import create_app
from app.config import get_bind_host, get_bind_port

app = create_app()

if __name__ == "__main__":
    host = get_bind_host()
    port = get_bind_port()
    print(f"Serving app on http://{host}:{port}")
    serve(app, host=host, port=port)

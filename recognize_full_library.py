from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
BACKEND_DIR = ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.recognition.avatar.full_library import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())

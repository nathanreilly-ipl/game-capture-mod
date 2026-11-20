"""Where outputs go. Everything is under OUT (default <repo>/out, gitignored);
set CAPTURE_OUT to move it, e.g. to a shared drive for several workers."""
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.environ.get("CAPTURE_OUT") or os.path.join(REPO, "out")

LOCATIONS = os.path.join(OUT, "locations", "locations.json")
QUEUE = os.path.join(OUT, "queue")
TAKES = os.path.join(OUT, "takes")

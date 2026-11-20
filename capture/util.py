import datetime
import hashlib
import json
import os
import re
import time


def now_iso():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def stamp():
    return time.strftime("%Y%m%d_%H%M%S")


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_file(path):
    with open(path, "rb") as f:
        return sha256_bytes(f.read())


def digest_json(obj):
    return sha256_bytes(json.dumps(obj, sort_keys=True, separators=(",", ":")).encode())


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "x"


def read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _json_default(o):
    """numpy arrays and scalars (e.g. in a solved rig's record) as plain JSON."""
    if hasattr(o, "tolist"):
        return o.tolist()
    if hasattr(o, "item"):
        return o.item()
    raise TypeError("Object of type %s is not JSON serializable" % type(o).__name__)


def write_json(path, obj, indent=1):
    """Writes through a temp file so a reader never sees a partial file."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=indent, default=_json_default)
    for _ in range(100):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            time.sleep(0.02)
    os.replace(tmp, path)

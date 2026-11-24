"""Frames from the capture add-on, asked for from Python. Game-agnostic.

In RDR2, GTA V and Cyberpunk 2077 the in-game script writes the add-on's request file itself. A
game whose scripts cannot write files (The Witcher 3) has its adapter ask instead, with this
module: the same files, in the folder ReShade.ini names as [CAPTURE_MOD] OutputDir.

    request.txt   id, name (a relative image stem), optionally after=<n> (the n-th frame presented
                  after the add-on sees the request) or op=frame (no picture)
    ack.txt       id, status, message, file, width, height, frame (frames presented since the
                  add-on loaded), time_ms
"""
import os
import time
import uuid


class FrameError(RuntimeError):
    pass


def _ask(exchange, fields, timeout):
    rid = uuid.uuid4().hex[:12]
    os.makedirs(exchange, exist_ok=True)
    ack = os.path.join(exchange, "ack.txt")
    tmp = os.path.join(exchange, "request.tmp")
    with open(tmp, "w", newline="\n") as f:
        f.write("id=%s\n" % rid + "".join("%s=%s\n" % kv for kv in fields.items()))
    os.replace(tmp, os.path.join(exchange, "request.txt"))
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            got = dict(line.rstrip("\n").split("=", 1) for line in open(ack) if "=" in line)
        except OSError:
            got = {}
        if got.get("id") == rid:
            if got.get("status") != "ok":
                raise FrameError("the capture add-on answered: %s" % (got.get("message") or got))
            return got
        time.sleep(0.004)
    try:
        os.remove(os.path.join(exchange, "request.txt"))   # nobody took it: do not leave it for a later frame
    except OSError:
        pass
    raise FrameError("no answer from the capture add-on in %.0f s (is the game rendering, and ReShade with the "
                     "add-on loaded?)" % timeout)


def counter(exchange, timeout=10.0):
    """{"frame": frames presented so far, "time_ms": the add-on's clock, "width", "height"}."""
    a = _ask(exchange, {"op": "frame"}, timeout)
    return {"frame": int(a["frame"]), "time_ms": int(a["time_ms"]), "width": int(a["width"]), "height": int(a["height"])}


def shoot(exchange, stem, after=0, timeout=60.0):
    """Saves a frame as <exchange>/<stem>.bmp: the one being presented when the add-on sees the
    request, or the `after`-th one after it. Returns the ack with "path" added."""
    a = _ask(exchange, {"name": stem, "after": int(after)}, timeout)
    a["path"] = os.path.join(exchange, *a["file"].split("/"))
    a["width"], a["height"], a["frame"] = int(a["width"]), int(a["height"]), int(a["frame"])
    return a


def wait(exchange, n, timeout=60.0):
    """Lets n frames be presented (measured by the add-on's counter). Returns the frame rate seen."""
    a = counter(exchange, timeout)
    target, t0 = a["frame"] + int(n), time.time()
    while True:
        time.sleep(0.01)
        b = counter(exchange, timeout)
        if b["frame"] >= target:
            dt = (b["time_ms"] - a["time_ms"]) / 1000.0
            return (b["frame"] - a["frame"]) / dt if dt > 0 else 0.0
        if time.time() - t0 > timeout:
            raise FrameError("only %d of %d frames in %.0f s" % (b["frame"] - a["frame"], n, timeout))


def frame_rate(exchange, seconds=1.0):
    a = counter(exchange)
    time.sleep(seconds)
    b = counter(exchange)
    dt = (b["time_ms"] - a["time_ms"]) / 1000.0
    return (b["frame"] - a["frame"]) / dt if dt > 0 else 0.0

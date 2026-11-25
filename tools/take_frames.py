"""Where a take's frame is: the file its capture log names, or, in a take sent for QC (docs/QC_LOOP.md),
the same name as JPEG or PNG. Game-agnostic; used by the tools that read frames through
capture_log.jsonl, so they run on a QC round's data as well as on the capturing machine's takes.
"""
import os

EXTS = (".jpg", ".jpeg", ".png", ".bmp")


def frame_file(take, logged):
    """The path of a logged frame ("raw/t001_near_moving_000.bmp"), or None if no version of it is
    there (a QC round sends a subset of a near sweep's poses)."""
    p = os.path.join(take, logged)
    if os.path.exists(p):
        return p
    stem = os.path.splitext(p)[0]
    for ext in EXTS:
        if os.path.exists(stem + ext):
            return stem + ext
    return None

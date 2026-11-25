"""Builds a game's QC round on the capturing machine and uploads it (docs/QC_LOOP.md, step 3).

    uv run --project . python tools/qc_round.py <game> <round> [--takes <take folder> ...]
        [--sweep-every 6] [--quality 92] [--notes notes.json] [--changes "first round"] [--upload]

Without --takes, the newest packaged take of each kind (near sweep, clip over time) at each of the
game's locations under out/takes. Per take, under out/qc_out/<game>/round-NN/<location>__<stamp>/:

- capture_log.jsonl, steps.jsonl, shots.json, take.json, as the take has them;
- raw/: full-resolution frames as JPEG (quality --quality, 4:2:0) under the stems the capture log
  names (the log says .bmp; tools/take_frames.py finds the .jpg): every camera at every clip frame
  of a clip over time, and of a near sweep every --sweep-every'th pose plus the poses around the
  ones tools/sweep_flicker.py flags, and the first and last;
- videos/: the preview videos (package/*/rgb.mp4, re-encoded under 10 MB where larger);
- sheets/: the take's sheets as JPEG;
- metrics/: tools/temporal_flicker.py or tools/sweep_flicker.py on the full take (JSON lines and
  their maps), run here because the round holds only some of a sweep's poses.

manifest.json beside the takes: game, round, commit (HEAD, pushed: the tools), each take's data,
the commit it was made with, known problem spots (--notes: {location id: [text, ...]}), what changed
since the last round and the tools new since then. --upload syncs it to
s3://data-interns/nathan.reilly/transfer-qc/<game>/round-NN/ (--s3-root to change).
"""
import argparse
import glob
import json
import os
import shutil
import subprocess
import sys

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
from capture import paths  # noqa: E402
from capture.package import ffmpeg_exe  # noqa: E402

S3_ROOT = "s3://data-interns/nathan.reilly/transfer-qc"
TOOLS = "uv run --project . python tools/"


def _git(*args):
    return subprocess.run(["git", "-C", ROOT] + list(args), capture_output=True, text=True).stdout.strip()


def kind_of(take):
    t = json.load(open(os.path.join(take, "take.json"), encoding="utf-8"))
    last = int((t.get("settings") or {}).get("last_frame") or 0)
    return ("clip" if last > 1 else "sweep"), t


def newest_takes(game):
    """The newest packaged take of each kind at each location of the game."""
    best = {}
    for tj in glob.glob(os.path.join(paths.OUT, "takes", game + "-*", "*", "*", "take.json")):
        take = os.path.dirname(tj)
        if not glob.glob(os.path.join(take, "package", "*", "rgb.mp4")) or not os.path.isdir(os.path.join(take, "raw")):
            continue
        kind, t = kind_of(take)
        key = (t["location"]["id"], kind)
        if key not in best or t.get("started", "") > best[key][0]:
            best[key] = (t.get("started", ""), take)
    return [best[k][1] for k in sorted(best)]


def log_rows(take):
    with open(os.path.join(take, "capture_log.jsonl"), encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def sweep_metrics(take, dest):
    out = subprocess.run([sys.executable, os.path.join(HERE, "sweep_flicker.py"), take, "--out", dest],
                         capture_output=True, text=True, cwd=ROOT)
    lines = [l for l in out.stdout.splitlines() if l.startswith("{")]
    with open(os.path.join(dest, "sweep_flicker.jsonl"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return json.loads(lines[-1]) if lines else {}


def clip_metrics(take, dest):
    out = subprocess.run([sys.executable, os.path.join(HERE, "temporal_flicker.py"), take, "--out", dest],
                         capture_output=True, text=True, cwd=ROOT)
    lines = [l for l in out.stdout.splitlines() if l.startswith("{")]
    with open(os.path.join(dest, "temporal_flicker.jsonl"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return [json.loads(l) for l in lines]


def video(src, dst):
    if os.path.getsize(src) < 9_500_000:
        shutil.copyfile(src, dst)
        return
    ff = ffmpeg_exe()
    dur = float(subprocess.run([os.path.join(os.path.dirname(ff), "ffprobe") if os.path.exists(
        os.path.join(os.path.dirname(ff), "ffprobe")) else "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "csv=p=0", src], capture_output=True, text=True).stdout.strip() or 12)
    kbps = int(9.2e6 * 8 / 1000 / max(dur, 1.0))
    log = dst + ".pass"
    subprocess.run([ff, "-y", "-v", "error", "-i", src, "-c:v", "libx264", "-b:v", "%dk" % kbps, "-pass", "1",
                    "-passlogfile", log, "-an", "-f", "mp4", os.devnull], check=True)
    subprocess.run([ff, "-y", "-v", "error", "-i", src, "-c:v", "libx264", "-b:v", "%dk" % kbps, "-pass", "2",
                    "-passlogfile", log, "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-an", dst], check=True)
    for p in glob.glob(log + "*"):
        os.remove(p)


def build_take(take, dest, sweep_every, quality, notes):
    kind, t = kind_of(take)
    loc = t["location"]["id"]
    name = "%s__%s" % (loc, os.path.basename(take))
    d = os.path.join(dest, name)
    for sub in ("raw", "videos", "sheets", "metrics"):
        os.makedirs(os.path.join(d, sub), exist_ok=True)
    for f in ("capture_log.jsonl", "steps.jsonl", "shots.json", "take.json", "npc_tracks.jsonl"):
        if os.path.exists(os.path.join(take, f)):
            shutil.copyfile(os.path.join(take, f), os.path.join(d, f))
    rows = [r for r in log_rows(take) if r.get("accepted")]
    flagged = []
    if kind == "sweep":
        m = sweep_metrics(take, os.path.join(d, "metrics"))
        flagged = [int(w["pose"]) for w in m.get("worst", [])]
        rows.sort(key=lambda r: r["name"])
        keep = {0, len(rows) - 1} | {i for i in range(len(rows)) if i % sweep_every == 0}
        for p in flagged:
            keep |= {i for i in range(p - 2, p + 3) if 0 <= i < len(rows)}
        rows = [r for i, r in enumerate(rows) if i in keep]
        frames_what = "near sweep: every %dth pose, the first and last, and +-2 around the poses sweep_flicker flags %s" % (
            sweep_every, flagged)
        metrics = {k: m.get(k) for k in ("roughness", "share_over_12", "brightness_jitter", "worst")}
    else:
        ms = clip_metrics(take, os.path.join(d, "metrics"))
        frames_what = "every camera at every clip frame"
        metrics = {m["camera"]: {k: m.get(k) for k in ("roughness", "share_over_12", "brightness_jitter",
                                                       "first_step_ratio", "exposure_drift", "pop_count", "pops")}
                   for m in ms}
    for r in rows:
        src = os.path.join(take, r["file"])
        stem = os.path.splitext(r["file"])[0]
        Image.open(src).convert("RGB").save(os.path.join(d, stem + ".jpg"), "JPEG", quality=quality)
    # evidence (tools/qc_evidence.py) and the NPC tracks (tools/npc_tracks.py) from the full take
    subprocess.run([sys.executable, os.path.join(HERE, "qc_evidence.py"), take, "--out", os.path.join(d, "evidence")],
                   capture_output=True, text=True, cwd=ROOT)
    if os.path.exists(os.path.join(take, "npc_tracks.jsonl")):
        subprocess.run([sys.executable, os.path.join(HERE, "npc_tracks.py"), take, "--out", os.path.join(d, "metrics")],
                       capture_output=True, text=True, cwd=ROOT)
    for v in glob.glob(os.path.join(take, "package", "*", "rgb.mp4")):
        video(v, os.path.join(d, "videos", os.path.basename(os.path.dirname(v)) + ".mp4"))
    for s in glob.glob(os.path.join(take, "sheets", "*.png")):
        im = Image.open(s).convert("RGB")
        if im.width > 2400:
            im = im.resize((2400, round(im.height * 2400 / im.width)))
        im.save(os.path.join(d, "sheets", os.path.basename(s)[:-4] + ".jpg"), quality=88)
    made_with = t.get("commit") or (_git("log", "-1", "--format=%h", "--before=" + t.get("started", "")) +
                                     " (the last commit before the take started; takes before 2026-11-25 did not record it)")
    return {"take": name, "location": loc, "title": t["location"].get("title"), "kind": kind,
            "source": os.path.relpath(take, paths.OUT), "started": t.get("started"), "made_with": made_with,
            "shots": t.get("n_shots"), "clip_frames": int((t.get("settings") or {}).get("last_frame") or 0) or 1,
            "cameras": (t.get("settings") or {}).get("cameras"), "frames_sent": len(rows), "frames": frames_what,
            "metrics": metrics, "known": (notes or {}).get(loc, [])}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("game")
    ap.add_argument("round", type=int)
    ap.add_argument("--takes", nargs="*")
    ap.add_argument("--sweep-every", type=int, default=6)
    ap.add_argument("--quality", type=int, default=92)
    ap.add_argument("--notes", help="JSON file: {location id: [known problem spots]}")
    ap.add_argument("--changes", default="first round")
    ap.add_argument("--tools-new", default="", help="what is new in the tools since the last round")
    ap.add_argument("--upload", action="store_true")
    ap.add_argument("--s3-root", default=S3_ROOT)
    a = ap.parse_args()
    rnd = "round-%02d" % a.round
    dest = os.path.join(paths.OUT, "qc_out", a.game, rnd)
    if os.path.exists(dest):
        shutil.rmtree(dest)
    os.makedirs(dest)
    takes = a.takes or newest_takes(a.game)
    notes = json.load(open(a.notes, encoding="utf-8")) if a.notes else {}
    entries = []
    for take in takes:
        e = build_take(take, dest, a.sweep_every, a.quality, notes)
        entries.append(e)
        print("%s: %d frames (%s)" % (e["take"], e["frames_sent"], e["kind"]), flush=True)
    manifest = {
        "game": a.game, "round": a.round, "commit": _git("rev-parse", "--short", "HEAD"),
        "created_on": "CoreWeave (Linux)", "takes": entries,
        "data_per_take": ["capture_log.jsonl, steps.jsonl, shots.json, take.json",
                          "raw/: full-resolution frames as JPEG quality %d (4:2:0) under the capture log's stems (the log "
                          "says .bmp; tools/take_frames.py finds the .jpg); which frames: see each take's 'frames'" % a.quality,
                          "videos/: the preview videos (package/*/rgb.mp4, under 10 MB each)",
                          "sheets/: the take's sheets (sweep, time, ring) as JPEG",
                          "metrics/: temporal_flicker.py or sweep_flicker.py on the full take (all poses), with their maps; "
                          "npc_tracks.json and its map where the take has npc_tracks.jsonl (takes from 2026-11-25)",
                          "evidence/: tools/qc_evidence.py on the full take: timestamps.md, per camera a strip of every clip "
                          "frame and the differences between neighbouring clip frames, crops around pops, flagged sweep poses "
                          "with their neighbours (index.md lists them)"],
        "changes_since_last_round": a.changes,
        "tools_new": a.tools_new,
        "tools_hint": "Every tool reads a take folder here: %stemporal_flicker.py <take>, %sclip_strip.py <take> "
                      "<camera> <out.jpg>, %ssweep_flicker.py <take> (on the poses sent). Numbers from these JPEG frames "
                      "run higher than metrics/ (made here from the lossless frames): compression adds to roughness "
                      "(RDR2 Rhodes, a fixed camera: 0.48 on the JPEGs, 0.26 lossless); metrics/ is the reference, the "
                      "tools on the JPEGs are for finding where." % (TOOLS, TOOLS, TOOLS),
    }
    with open(os.path.join(dest, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=1)
    size = sum(os.path.getsize(os.path.join(r, n)) for r, _, ns in os.walk(dest) for n in ns)
    print("%s: %d takes, %.0f MB in %s" % (rnd, len(entries), size / 1e6, dest))
    if a.upload:
        url = "%s/%s/%s/" % (a.s3_root.rstrip("/"), a.game, rnd)
        subprocess.run(["aws", "s3", "sync", dest, url, "--only-show-errors"], check=True)
        print("uploaded to", url)
    return 0


if __name__ == "__main__":
    sys.exit(main())

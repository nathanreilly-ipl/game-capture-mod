"""Command line: python -m capture <command> (or .\\capture.ps1 <command> from the repo root).

    scout      record a location (and its 4 outward previews) from the running game
    locations  list the recorded locations
    submit     queue a rig for one or more locations
    queue      show the queue; retry a failed job; requeue stale claims
    worker     take jobs from the queue and capture them
    package    package a captured take (the worker does this itself)
    sheets     render sheets for a captured take
"""
import argparse
import os
import sys

from . import adapters_registry, paths
from . import locations as locs
from .package import package
from .queue import Queue
from .runner import DEFAULT_SETTINGS
from .sheets import make_sheets


def _xyz(text):
    v = [float(x) for x in text.split(",")]
    if len(v) != 3:
        raise argparse.ArgumentTypeError("expected x,y,z")
    return v


def cmd_scout(a):
    from .scout import TooClose, scout
    adapter = adapters_registry.get(a.game)()
    adapter.ensure_ready(restart=False)
    try:
        scout(adapter, a.locations, name=a.name, at=a.at, facing=a.facing,
              clock=None if a.clock == "keep" else a.clock,
              tags=[t for t in a.tags.split(",") if t], note=a.note, force=a.force)
    except TooClose as e:
        raise SystemExit(str(e))
    finally:
        adapter.close()


def cmd_locations(a):
    doc = locs.load(a.locations)
    if a.titles or a.publish:
        for game in sorted({loc["game"] for loc in doc["locations"]}):
            adapter = adapters_registry.get(game)()
            if a.titles:
                adapter.ensure_ready(restart=False)
                adapter.open()
                try:
                    for loc in doc["locations"]:
                        if loc["game"] == game and not loc.get("title"):
                            loc["title"] = adapter.place_title(loc["position"])
                finally:
                    adapter.close()
                locs.save(a.locations, doc)
            adapter.publish_locations(doc["locations"])
    for loc in doc["locations"]:
        print("%-24s %-44s %s  facing %6.1f  %s" % (
            loc["id"], loc.get("title") or "-", ", ".join("%.1f" % v for v in loc["position"]),
            loc.get("facing_deg", 0), ",".join(loc.get("tags", []))))
    print("%d locations in %s" % (len(doc["locations"]), a.locations))


def cmd_submit(a):
    doc = locs.load(a.locations)
    chosen = [loc for loc in doc["locations"]
              if (a.all or loc["id"] in a.location) and (not a.game or loc["game"] == a.game)]
    missing = set(a.location) - {loc["id"] for loc in doc["locations"]}
    if missing:
        raise SystemExit("unknown locations: " + ", ".join(sorted(missing)))
    if not chosen:
        raise SystemExit("no locations chosen (use --location ID or --all)")
    q = Queue(a.queue)
    rig = q.add_rig(a.rig)
    settings = {"clock": None if a.clock == "keep" else a.clock, "last_frame": a.last_frame,
                "sweep_stride": a.sweep_stride, "keep_raw": not a.no_keep_raw, "adapter": {}}
    if a.cameras:
        settings["cameras"] = [p for p in a.cameras.split(",") if p]
    if a.settle is not None:
        settings["adapter"]["settle"] = a.settle
    for loc in chosen:
        job_id, state, new = q.submit(loc["game"], loc, rig, settings, force=a.force)
        print("%s %s" % ("queued " if new else "exists (%s)" % state, job_id))


def cmd_queue(a):
    q = Queue(a.queue)
    if a.action == "retry":
        for job_id in a.ids:
            q.retry(job_id)
            print("pending", job_id)
        return
    if a.action == "requeue":
        for job_id in q.requeue_stale(a.stale_s):
            print("requeued", job_id)
        return
    for state, ids in q.status().items():
        print("%-8s %d" % (state, len(ids)))
        for job_id in ids:
            line = "  " + job_id
            if state in ("done", "failed"):
                _, job = q.load(job_id)
                extra = job.get("result", {}).get("take_dir") if state == "done" else job.get("error", {}).get("message")
                line += "  " + str(extra)
            print(line)


def cmd_worker(a):
    from .worker import run_worker
    n = run_worker(a.game, a.queue, a.takes, worker_id=a.worker_id, once=a.once, restart=not a.no_restart)
    print("%d jobs" % n)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="capture", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--locations", default=paths.LOCATIONS, help="locations file (default %(default)s)")
    ap.add_argument("--queue", default=paths.QUEUE, help="queue folder (default %(default)s)")
    ap.add_argument("--takes", default=paths.TAKES, help="takes folder (default %(default)s)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("scout", help="record a location from the running game")
    s.add_argument("--game", default="rdr2", choices=adapters_registry.names())
    s.add_argument("--name", help="short name for the id, e.g. lakeshore")
    s.add_argument("--at", type=_xyz, help="x,y,z: move the player there first")
    s.add_argument("--facing", type=float, help="facing in degrees (default: the player's)")
    s.add_argument("--clock", default="12:00", help="time of day for the previews, HH:MM or 'keep'")
    s.add_argument("--tags", default="")
    s.add_argument("--note", default="")
    s.add_argument("--force", action="store_true", help="save even within 5 m of a saved location")
    s.set_defaults(fn=cmd_scout)

    s = sub.add_parser("locations", help="list locations")
    s.add_argument("--titles", action="store_true", help="fill in missing place titles from the running game")
    s.add_argument("--publish", action="store_true", help="refresh the list the in-game scout overlay shows")
    s.set_defaults(fn=cmd_locations)

    s = sub.add_parser("submit", help="queue a rig for locations")
    s.add_argument("--rig", required=True, help="a camrig/v1 file")
    s.add_argument("--location", action="append", default=[], help="location id (repeatable)")
    s.add_argument("--all", action="store_true", help="every location (of --game, if given)")
    s.add_argument("--game")
    s.add_argument("--clock", default=DEFAULT_SETTINGS["clock"], help="HH:MM or 'keep'")
    s.add_argument("--last-frame", type=int, default=0, help="stop after this clip frame (a sample)")
    s.add_argument("--sweep-stride", type=int, default=1, help="every n-th sweep pose (a sample)")
    s.add_argument("--cameras", help="only these rig cameras, comma-separated name patterns "
                                     "(e.g. '?_near_sweep_t000' = the near frozen sweep)")
    s.add_argument("--settle", type=int, help="game-specific settle after each camera move (RDR2: ticks, 40)")
    s.add_argument("--no-keep-raw", action="store_true", help="delete raw frames after packaging")
    s.add_argument("--force", action="store_true", help="queue again even if the same job exists")
    s.set_defaults(fn=cmd_submit)

    s = sub.add_parser("queue", help="show or manage the queue")
    s.add_argument("action", nargs="?", default="status", choices=("status", "retry", "requeue"))
    s.add_argument("ids", nargs="*")
    s.add_argument("--stale-s", type=float, default=900)
    s.set_defaults(fn=cmd_queue)

    s = sub.add_parser("worker", help="capture queued jobs")
    s.add_argument("--game", default="rdr2", choices=adapters_registry.names())
    s.add_argument("--once", action="store_true", help="one job at most, then exit")
    s.add_argument("--worker-id")
    s.add_argument("--no-restart", action="store_true", help="never restart the game")
    s.set_defaults(fn=cmd_worker)

    s = sub.add_parser("package", help="package a take")
    s.add_argument("take")
    s.set_defaults(fn=lambda a: package(a.take))

    s = sub.add_parser("sheets", help="render sheets for a take")
    s.add_argument("take")
    s.add_argument("--out")
    s.set_defaults(fn=lambda a: make_sheets(a.take, a.out))

    a = ap.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    sys.exit(main())

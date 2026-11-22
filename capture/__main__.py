"""Command line: python -m capture <command> (or .\\capture.ps1 <command> from the repo root).

    install    install everything a game needs (mods, ReShade, our add-on and scripts, settings)
    verify     check that an install can scout, capture and iterate
    uninstall  put back what install changed
    mods       the third-party files an install needs: status, fetch, bundle, docs
    scout      record a location (and its 4 outward previews) from the running game
    locations  list the recorded locations
    providers  list the rig providers (rig formats) this machine can use
    solve      a provider's rig at a location, with a plan image, without a take
    submit     queue a rig for one or more locations
    queue      show the queue; retry a failed job; requeue stale claims
    worker     take jobs from the queue and capture them
    package    package a captured take (the worker does this itself)
    sheets     render sheets for a captured take
"""
import argparse
import json
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
            if a.titles and any(loc["game"] == game and not loc.get("title") for loc in doc["locations"]):
                try:
                    adapter.ensure_ready(restart=False)
                except Exception as e:
                    print("titles for %s skipped: %s" % (game, e))
                    continue
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
    rig = q.add_provider(*_provider_args(a))
    print("rig %s: provider %s %s" % (rig["rig_id"], rig["provider"], rig["version"]))
    settings = {"clock": None if a.clock == "keep" else a.clock, "last_frame": a.last_frame,
                "sweep_stride": a.sweep_stride, "keep_raw": not a.no_keep_raw, "adapter": {}}
    if a.cameras:
        settings["cameras"] = [p for p in a.cameras.split(",") if p]
    if a.settle is not None:
        settings["adapter"]["settle"] = a.settle
    if a.park_height is not None:
        settings["adapter"]["park_height"] = a.park_height
    for key in ("obstacle_margin", "retake_before", "max_retakes"):
        if getattr(a, key) is not None:
            settings[key] = getattr(a, key)
    if a.no_obstacle_check:
        settings["obstacle_check"] = False
    if a.qc:
        settings["qc"] = a.qc
    for loc in chosen:
        job_id, state, new = q.submit(loc["game"], loc, rig, settings, force=a.force)
        print("%s %s" % ("queued " if new else "exists (%s)" % state, job_id))


def _parse_value(text):
    try:
        return json.loads(text)
    except ValueError:
        return text


def _provider_args(a):
    """(provider, settings, subject) from --rig / --solver / --provider and --set key=value."""
    given = [x for x in (a.rig, a.solver, a.provider) if x]
    if len(given) != 1:
        raise SystemExit("give one of --rig <camrig/v1 file>, --solver <camrigs rig key>, --provider <key or file>")
    settings = {}
    for kv in a.set or []:
        k, _, v = kv.partition("=")
        settings[k.strip()] = _parse_value(v.strip())
    if a.rig:
        key, settings["path"] = "file", a.rig
    elif a.solver:
        key, settings["rig"] = "camrigs", a.solver
    else:
        key = a.provider
    subject = {k: v for k, v in (("height_m", a.subject_height), ("radius_m", a.subject_radius)) if v is not None}
    return key, settings, subject


def cmd_providers(a):
    from .providers import listing
    for p in listing():
        if p.get("key") is None:
            print("%-10s ERROR %s (%s)" % ("?", p["error"], p["file"]))
        else:
            print("%-10s %-4s %s\n           %s%s" % (p["key"], "ok" if p["available"] else "--", p["title"], p["file"],
                                                    "" if p["available"] else "\n           not available: " + p["why"]))


def cmd_solve(a):
    """Capture a location's scene, ask a rig provider for its rig there, draw the plan; no take."""
    from . import rigplot
    from .rigs import resolve, scene_for
    loc = locs.get(a.locations, a.location)
    adapter = adapters_registry.get(loc["game"])()
    adapter.ensure_ready(restart=False)
    adapter.open()
    scene_dir = os.path.join(os.path.dirname(a.locations), "scenes")
    try:
        src = Queue(a.queue).add_provider(*_provider_args(a))
        rig, path = resolve(src, base_dir=a.queue, location=loc, adapter=adapter,
                            out_dir=os.path.join(paths.OUT, "solved"), scene_dir=scene_dir)
        sc = scene_for(adapter, loc, src.get("scene"), scene_dir) if "raycast" in adapter.capabilities else None
    finally:
        adapter.close()
    fit = rig.get("record", {}).get("scene_fit", {})
    out = path[:-5] + "_plan.png"
    title = "%s, %s, %d cameras" % (loc["id"], src["rig_id"], len(rig["cameras"]))
    rigplot.plan(sc.points if sc is not None else [], rig, title).save(out)
    print("%d cameras; effects: %s" % (len(rig["cameras"]), fit.get("effects") or "none"))
    print("rig:", path)
    print("plan:", out)


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


def _install_options(a):
    def flag(on, off):  # None: the game's default
        return False if off else True if on else None
    return {"optiscaler": flag(a.optiscaler, a.no_optiscaler), "native_trainer": False if a.no_native_trainer else None,
            "preset": flag(getattr(a, "preset", False), a.no_preset), "ray_tracing": flag(a.ray_tracing, a.no_ray_tracing),
            "graphics_mod": flag(a.graphics_mod, a.no_graphics_mod), "api": a.api, "resolution": a.resolution,
            "dlss_mode": getattr(a, "dlss_mode", None)}


def _mods_roots(a):
    roots = list(a.mods or [])
    if getattr(a, "dlss_nr", None):
        roots.append(a.dlss_nr)
    return roots


def cmd_install(a):
    from . import install as inst
    from .install import prereqs
    try:
        if not a.only:
            print("machine:")
            prereqs.report(_install_options(a))
            print("steps:")
        n = inst.install(a.game, a.game_dir, _install_options(a), _mods_roots(a), only=a.only, dry_run=a.dry_run)
    except inst.InstallError as e:
        raise SystemExit("install stopped: %s" % e)
    if not a.dry_run and not a.only and not a.no_verify:
        print("next: .\\capture.ps1 verify %s --launch   (starts the game and checks everything works)" % a.game)
    return n


def cmd_uninstall(a):
    from . import install as inst
    ctx, mod = inst.context(a.game)
    if ctx.system.process_running(mod.EXE):
        raise SystemExit("close the game first")
    inst.uninstall(a.game)


def cmd_verify(a):
    from .install.verify import verify
    if not verify(a.game, launch=a.launch, quick=a.quick):
        raise SystemExit(1)


def cmd_mods(a):
    from . import install as inst
    from .install import docs, sources
    from .install.components import addon
    if a.action == "docs":
        print("wrote", docs.generate())
        return
    ctx, mod = inst.context(a.game, a.game_dir, None, _mods_roots(a))
    if a.action == "fetch":
        sources.fetch(ctx.files)
    elif a.action == "bundle":
        out = a.output or os.path.join(paths.OUT, "bundles", "capture-mods-%s.zip" % a.game)
        extra = [("capture_addon/" + addon.NAME, addon.BUILT), ("capture_addon/" + addon.STAMP, addon.BUILT_STAMP)] if addon.is_built() else []
        if not extra:
            print("the capture add-on is not built here, so the bundle will not include it")
        sources.bundle(ctx.files, out, with_supplied=a.with_supplied, extra=extra)
    else:
        print("looking in: %s" % ", ".join(ctx.files.roots + ["the existing install"]))
        for mod_id, m, refs in ctx.files.status():
            print("%s  [%s%s]" % (m["title"], "required" if m.get("required") else "optional",
                                  ", download" if m.get("source") == "download" else ", supply yourself"))
            for r in refs:
                print("  %-8s %-22s %s" % ("found" if r.found else "MISSING", r.spec["name"], r.where or "get it from " + str(m.get("page"))))
            if not refs:
                print("  (files not pinned yet)")
        from .install.components import pack
        for mod_id, m in ctx.files.packs():
            src = pack.find_source(m, ctx.files.roots)
            print("%s  [optional, supply yourself; %d files from its archive]" % (m["title"], len(m.get("files", []))))
            print("  %-8s %-22s %s" % ("found" if src else "MISSING", m["archive"]["name"][:22],
                                       src or "get it from " + str(m.get("page"))))
        print("what each file is and where to get it: docs/MOD_FILES.md")


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

    def rig_args(s):
        s.add_argument("--provider", help="a rig provider: a key (capture providers) or a .py file (rigs/README.md)")
        s.add_argument("--set", action="append", metavar="KEY=VALUE",
                       help="a provider setting (repeatable; JSON values allowed), e.g. --set seed=7")
        s.add_argument("--rig", help="shortcut: --provider file --set path=<camrig/v1 file>")
        s.add_argument("--solver", help="shortcut: --provider camrigs --set rig=<key>, e.g. yiming_stdm")
        s.add_argument("--subject-height", type=float, help="stand-in subject height, m (default 1.996)")
        s.add_argument("--subject-radius", type=float, help="stand-in subject half width, m (default 0.534)")

    s = sub.add_parser("providers", help="list the rig providers this machine can use")
    s.set_defaults(fn=cmd_providers)

    s = sub.add_parser("submit", help="queue a rig for locations")
    rig_args(s)
    s.add_argument("--qc", choices=("flag", "fail", "off"),
                   help="the provider's check of the packaged take: record it (flag, default), fail the job, or skip")
    s.add_argument("--location", action="append", default=[], help="location id (repeatable)")
    s.add_argument("--all", action="store_true", help="every location (of --game, if given)")
    s.add_argument("--game")
    s.add_argument("--clock", default=DEFAULT_SETTINGS["clock"], help="HH:MM or 'keep'")
    s.add_argument("--last-frame", type=int, default=0, help="stop after this clip frame (a sample)")
    s.add_argument("--sweep-stride", type=int, default=1, help="every n-th sweep pose (a sample)")
    s.add_argument("--cameras", help="only these rig cameras, comma-separated name patterns "
                                     "(e.g. '?_near_sweep_t000' = the near frozen sweep)")
    s.add_argument("--settle", type=int, help="game-specific settle after each camera move (RDR2: ticks, 40)")
    s.add_argument("--park-height", type=float,
                   help="park the hidden player this many metres above the location during the take "
                        "(RDR2; default 10, 0 = stay at the spot)")
    s.add_argument("--obstacle-margin", type=float,
                   help="metres around a person/animal/vehicle that count as inside it (default 0.15)")
    s.add_argument("--retake-before", type=float,
                   help="a camera inside something before this share of the shots: retake (default 0.667)")
    s.add_argument("--max-retakes", type=int, help="retakes of one job before it fails (default 3)")
    s.add_argument("--no-obstacle-check", action="store_true",
                   help="neither clear nor check people/animals/vehicles in the cameras")
    s.add_argument("--no-keep-raw", action="store_true", help="delete raw frames after packaging")
    s.add_argument("--force", action="store_true", help="queue again even if the same job exists")
    s.set_defaults(fn=cmd_submit)

    s = sub.add_parser("solve", help="a provider's rig at a location, with its plan (no take)")
    s.add_argument("--location", required=True)
    rig_args(s)
    s.set_defaults(fn=cmd_solve)

    s = sub.add_parser("queue", help="show or manage the queue")
    s.add_argument("action", nargs="?", default="status", choices=("status", "retry", "requeue"))
    s.add_argument("ids", nargs="*")
    s.add_argument("--stale-s", type=float, default=900)
    s.set_defaults(fn=cmd_queue)

    def game_args(s, mods=True):
        s.add_argument("game", choices=adapters_registry.names())
        s.add_argument("--game-dir", help="the folder holding the game's exe (default: found through Steam, "
                                          "or what the last install used)")
        if mods:
            s.add_argument("--mods", action="append", metavar="PATH",
                           help="a folder, archive or bundle holding mod files (repeatable; out/mods is always searched)")
            s.add_argument("--dlss-nr", metavar="FILE", help="your nvngx_dlssnr.dll, for --optiscaler")

    s = sub.add_parser("install", help="install everything a game needs")
    game_args(s)
    s.add_argument("--optiscaler", action="store_true",
                   help="install OptiScaler (DLSS 5; needs your nvngx_dlssnr.dll); the default for RDR2")
    s.add_argument("--no-optiscaler", action="store_true", help="leave OptiScaler out (it is not loaded)")
    s.add_argument("--no-native-trainer", action="store_true", help="leave out the game's trainer menu, where it has one")
    s.add_argument("--ray-tracing", action="store_true",
                   help="RDR2: Reality Redemption 2 (hardware ray tracing; Direct3D 12 only); the default for RDR2")
    s.add_argument("--no-ray-tracing", action="store_true", help="leave the ray tracing out")
    s.add_argument("--graphics-mod", action="store_true",
                   help="the game's graphics overhaul, where one is pinned: NaturalVision Enhanced for GTA V Enhanced "
                        "(its default)")
    s.add_argument("--no-graphics-mod", action="store_true", help="leave the graphics overhaul out (its files are removed)")
    s.add_argument("--preset", action="store_true",
                   help="the game's visual set (ReShade presets); the default for RDR2, off for GTA V")
    s.add_argument("--no-preset", action="store_true",
                   help="captures without ReShade effects (an empty preset) instead of the game's visual set")
    s.add_argument("--api", choices=("vulkan", "d3d12", "d3d11", "dxgi", "opengl"),
                   help="the graphics API (the game is switched to it; default: the game's install default, "
                        "Direct3D 12 for RDR2)")
    s.add_argument("--resolution", metavar="WxH",
                   help="the game's windowed size, 16:9 (default for RDR2: 2560x1440, the capture size)")
    s.add_argument("--dlss-mode", choices=("dlaa", "quality", "balanced", "performance"),
                   help="the DLSS mode under DLSS 5 (with --optiscaler; default dlaa, the full resolution in); "
                        "RDR2 takes dlaa or quality")
    s.add_argument("--only", action="append",
                   choices=("mods", "reshade", "addon", "scripts", "settings", "optiscaler", "raytracing", "graphicsmod",
                            "machine"),
                   help="only these parts (repeatable), e.g. --only scripts after editing a script")
    s.add_argument("--dry-run", action="store_true", help="show every step and what it would change; change nothing")
    s.add_argument("--no-verify", action="store_true", help=argparse.SUPPRESS)
    s.set_defaults(fn=cmd_install)

    s = sub.add_parser("verify", help="check that an install can scout, capture and iterate")
    s.add_argument("game", choices=adapters_registry.names())
    s.add_argument("--launch", action="store_true", help="start (or restart) the game if it is not ready")
    s.add_argument("--quick", action="store_true", help="skip the small test take")
    s.set_defaults(fn=cmd_verify)

    s = sub.add_parser("uninstall", help="put back what install changed")
    s.add_argument("game", choices=adapters_registry.names())
    s.set_defaults(fn=cmd_uninstall)

    s = sub.add_parser("mods", help="the third-party files an install needs")
    s.add_argument("action", choices=("status", "fetch", "bundle", "docs"))
    game_args(s)
    s.add_argument("-o", "--output", help="bundle: the zip to write (default out/bundles/capture-mods-<game>.zip)")
    s.add_argument("--with-supplied", action="store_true",
                   help="bundle: include files that may not be redistributed (for your own machines only)")
    s.set_defaults(fn=cmd_mods)

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

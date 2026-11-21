"""`capture install <game>`: everything a fresh machine needs to scout, capture and iterate.

Game-agnostic parts live here (the step framework, where mod files come from, and the
components every game shares: ReShade, our capture add-on, optional OptiScaler). Each game's
adapter adds its own mods and settings in adapters/<game>/install.py:

    GAME, TITLE, EXE, LOCK (its lockfile), OPTIONS (its options and defaults)
    find_game_dir() -> path or None
    installed_dirs(game_dir, system) -> folders of an existing install to search for pinned files
    steps(ctx) -> [Step]                (calls the shared components with the game's choices)
    after_install(ctx) -> [str]         (what to tell the user)
"""
import importlib
import os
import sys

from .. import config, paths
from .components import addon
from .plan import Ctx, InstallError, Record, System, run, uninstall as _uninstall
from .sources import SHARED_LOCK, Files, load_locks

INSTALLERS = {"rdr2": "adapters.rdr2.install", "gtav": "adapters.gtav.install"}


def installer(game):
    if game not in INSTALLERS:
        raise InstallError("no installer for %r (known: %s)" % (game, ", ".join(sorted(INSTALLERS))))
    if paths.REPO not in sys.path:
        sys.path.insert(0, paths.REPO)
    return importlib.import_module(INSTALLERS[game])


def work_dir(game):
    return os.path.join(paths.OUT, "install", game)


def context(game, game_dir=None, options=None, mods=(), system=None, work=None, log=print):
    mod = installer(game)
    system = system or System()
    game_dir = game_dir or mod.find_game_dir()
    if not game_dir or not os.path.exists(os.path.join(game_dir, mod.EXE)):
        raise InstallError("%s not found%s: pass --game-dir <the folder holding %s>" % (
            mod.TITLE, " in %s" % game_dir if game_dir else "", mod.EXE))
    game_dir = os.path.abspath(game_dir)
    record = Record(work or work_dir(game))
    if options is None:  # verify, mods status: the options the last install used
        options = {k: v for k, v in record.data.get("options", {}).items() if k in mod.OPTIONS}
    opts = dict(mod.OPTIONS, **{k: v for k, v in options.items() if v is not None})
    files = Files(load_locks(SHARED_LOCK, mod.LOCK), roots=mods, installed=mod.installed_dirs(game_dir, system),
                  extra_names=addon.EXTRA_NAMES)
    return Ctx(game, game_dir, mod.EXE, opts, files, record, system, log), mod


def install(game, game_dir=None, options=None, mods=(), only=None, dry_run=False, system=None, work=None, log=print):
    ctx, mod = context(game, game_dir, options, mods, system, work, log)
    log("%s in %s%s" % (mod.TITLE, ctx.game_dir, "  (dry run: nothing is changed)" if dry_run else ""))
    n = run(ctx, mod.steps(ctx), only=only, dry_run=dry_run)
    if dry_run:
        log("%d steps to do" % n)
        return n
    if work is None:
        config.set_game(game, game_dir=ctx.game_dir)
    ctx.record.save(game=game, game_dir=ctx.game_dir, options=ctx.options)
    log("%s" % ("%d steps applied" % n if n else "nothing to do: already installed"))
    if n and not only:
        for line in mod.after_install(ctx):
            log(line)
    return n


def uninstall(game, work=None, log=print):
    record = Record(work or work_dir(game))
    if not record.data["entries"]:
        log("nothing recorded for %s" % game)
        return
    _uninstall(record, log)

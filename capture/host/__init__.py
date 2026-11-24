"""The machine a game runs on. Game-agnostic.

On Windows a game runs as it is (windows.py). On Linux the same Windows game runs under Proton
inside the Steam Linux Runtime container, on a headless X display of its own (proton.py); the
in-game parts (script layer, loader, ReShade, our add-on and clock plug-in) are the same files and
run inside the game either way. What differs outside the game goes through this package, so
neither `capture/` nor an adapter asks which system it is on:

    pids(exe_name)                    the game's processes
    stop(game, exe_names)             end them (and, under Proton, everything else in its prefix)
    start(game, exe, args, ...)       start the game's exe
    check_start(game)                 raise if this process could not start the game (before closing one)
    start_beside_steam(game, exe, ...)  start the exe where the prefix's Steam client runs (a game that checks its licence with Steam)
    game_path(path, game)             a path of this machine as code inside the game sees it
    host_path(path, game)             a path the game gave, on this machine
    use_prefix(game, name)            the game shares the prefix `name` with others (one launcher, one sign-in)
    steam_launch(game, app_id)        asks the Steam client to start a game (under Proton: the client in the game's prefix)
    gpu_name()                        the GPU's name as the driver gives it (Linux)
    user_dir(game, kind)              the game user's folders (settings, saves)
    program_data(game)                the machine-wide data folder
    CLI                               how the command line is called here, for messages

`game` is the game's name in the adapters registry: under Proton each game has its own prefix
(out/proton/<game>), which is where its user folders are.

Adapters reach windows, keys and screen grabs through adapters/common/window.py and process memory
through adapters/common/mem.py, which pick their own implementation the same way.
"""
import os

LINUX = os.name != "nt"
WINDOWS = not LINUX
NAME = "linux" if LINUX else "windows"

if LINUX:
    from . import proton as _impl
else:
    from . import windows as _impl

CLI = _impl.CLI
pids = _impl.pids
stop = _impl.stop
start = _impl.start
check_start = _impl.check_start
start_beside_steam = _impl.start_beside_steam
game_path = _impl.game_path
host_path = _impl.host_path
use_prefix = _impl.use_prefix
steam_launch = _impl.steam_launch
app_overrides = getattr(_impl, "app_overrides", None)
prefix = getattr(_impl, "prefix", None)
gpu_name = _impl.gpu_name
user_dir = _impl.user_dir
program_data = _impl.program_data


def process_running(exe_name):
    return bool(pids(exe_name))

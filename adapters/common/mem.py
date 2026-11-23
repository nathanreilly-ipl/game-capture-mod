"""Read, search and write the memory of a running game, for finding engine data such as the
render camera. Game-agnostic: adapters pass their game's process name (adapters/<game>/mem.py
binds it).

The same names on either system: mem_win32.py on Windows, mem_linux.py where the game runs under
Proton (the game's memory is the same there, at the same addresses, read through /proc).

    find_pid(exe_name) -> pid                      RuntimeError if it is not running
    Process(pid=None, write=False, exe=None)       regions(), read(), write(), protect(), module(),
                                                   read_floats(), write_floats(), scan_vec3()
    PAGE_READWRITE, PAGE_EXECUTE_READWRITE, ...    the protection flags regions() reports
"""
import os

if os.name == "nt":
    from .mem_win32 import *   # noqa: F401,F403
else:
    from .mem_linux import *   # noqa: F401,F403

"""RDR2.exe's memory, through the shared helpers (adapters/common/mem.py)."""
from ..common.mem import *  # noqa: F401,F403
from ..common import mem as _mem

EXE = "RDR2.exe"


def find_pid(name=EXE):
    return _mem.find_pid(name)


class Process(_mem.Process):
    def __init__(self, pid=None, write=False):
        super().__init__(pid, write, exe=EXE)

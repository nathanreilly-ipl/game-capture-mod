"""Lua into the running Kingdom Come: Deliverance, and the answers back.

    uv run --project . python -m adapters.kcd.probes.repl --reload "=state" "System.GetCVar('t_Scale')" "=pose 100 200 30 0 1 0 60"

--reload    loads adapters/kcd/lua/capture_mod.lua into the running game first (no restart: the
            source goes over the console in pieces; session.load_lua)
=<op> args  runs our script's command (state, hello, pose, release, cvar, eval, ...)
+<lua>      any Lua through our script's eval, however long (statements: `return` gives the value)
<lua>       a short Lua expression through the console as it is (works before our script is
            loaded too) and its value printed
"""
import os
import sys

from ..session import Session

LUA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lua", "capture_mod.lua")


def num(v):
    try:
        return int(v)
    except ValueError:
        try:
            return float(v)
        except ValueError:
            return v


def main(argv):
    s = Session()
    if "--reload" in argv:
        argv = [a for a in argv if a != "--reload"]
        r = s.reload_script(open(LUA, encoding="utf-8").read())
        print("> reload capture_mod.lua  ->  %s %s" % ("ok" if r.ok else "ERROR", r.text))
    for a in argv:
        if a.startswith("="):
            parts = a[1:].split()
            op, args = parts[0], parts[1:]
            r = s.cmd(op, *[num(v) for v in args], check=False)
            print("> %s  ->  %s %s" % (a, "ok" if r.ok else "ERROR", r.text))
            for d in r.data:
                print("    " + d[:400])
            if r.state:
                print("    " + " ".join("%s=%s" % kv for kv in r.state.items()))
        elif a.startswith("+"):
            r = s.cmd("eval", a[1:], check=False, timeout=15.0)
            print("> %s  ->  %s %s" % (a[:80], "ok" if r.ok else "ERROR", r.text))
            for d in r.data:
                print("    " + d[:2000])
        else:
            print("> %s  ->  %s" % (a, s.raw(a)))


if __name__ == "__main__":
    main(sys.argv[1:])

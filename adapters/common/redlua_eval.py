"""Runs Lua in a RedLua game's capture session and prints the answer: the agent's way to try
natives while the game runs (RDR2, GTA V). The code is the body of function(ctx, native); what it
returns (a value or a list of values) is printed.

    python -m adapters.common.redlua_eval --game gtave "return ctx.call('MISC', 'GET_GAME_TIMER')"
    python -m adapters.common.redlua_eval --game rdr2 --file probe.lua      # a file with such a body

It opens the game's adapter (a capture session, as a take does) and closes it again afterwards.
"""
import argparse
import os
import sys

from capture import adapters_registry


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--game", required=True)
    ap.add_argument("--file")
    ap.add_argument("code", nargs="?")
    a = ap.parse_args(argv)
    body = open(a.file, encoding="utf-8").read() if a.file else a.code
    if not body:
        ap.error("give the code or --file")
    adapter = adapters_registry.get(a.game)()
    adapter.ensure_ready(restart=False)
    adapter.open()
    try:
        exchange = getattr(adapter, "exchange", None) or adapter.sess.exchange   # RDR2 keeps it on its session
        with open(os.path.join(exchange, "eval_in.lua"), "w", encoding="utf-8", newline="\n") as f:
            f.write("return function(ctx, native)\n%s\nend\n" % body)
        r = adapter.sess.cmd("eval", timeout=600)
        for k in sorted((k for k in r if k[:1] == "r" and k[1:].isdigit()), key=lambda k: int(k[1:])):
            print(r[k])
    finally:
        adapter.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

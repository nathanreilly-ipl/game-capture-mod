"""The QC loop on the machine that reviews (docs/QC_LOOP.md): rounds of a game's previews and QC data
from the capturing machine, reviewed by agents (headless Claude Code runs, or any command given),
their findings sent back. Game-agnostic: nothing here knows a game.

    capture qc config [--max-agents N] [--model M] [--claude PATH] [--agent-cmd CMD] [--s3-root URI]
    capture qc pull <game> <round> [--src DIR] [--keep-s3]   a round in from S3 (or a folder); the game queues
    capture qc run [--max-agents N] [--model M]              reviewers for the queue, first in first out
    capture qc review <game> <round>                         one reviewer for one game now
    capture qc report <game> <round>                         findings.json: ids, order, report.md
    capture qc push <game> <round> [--dest DIR]              the feedback out to S3 (or a folder); the game is in fixes
    capture qc status

A game is in one state at a time: queued (its round is here, waiting for a reviewer), reviewing,
reviewed (feedback ready to push), failed (the reviewer gave no usable findings) or fixes (with the
capturing machine). out/qc/state.json holds them; out/qc/<game>/round-NN/ holds a round: the data as
sent (manifest.json, one folder per take) and feedback/ (prompt.md, findings.json, report.md, the
agent's output).
"""
import contextlib
import datetime
import json
import os
import shlex
import shutil
import subprocess
import sys
import time

from . import config, paths
from .util import read_json, write_json

ROOT = os.path.realpath(os.path.join(paths.OUT, "qc"))   # long paths: a reviewer's tools check them
STATE = os.path.join(ROOT, "state.json")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROMPT = os.path.join(REPO, "docs", "qc", "reviewer.md")
CATEGORIES = ["geometry_continuity", "geometry_accuracy", "lighting_continuity", "lighting_accuracy",
              "npc_continuity", "npc_accuracy"]
# what a reviewer may do: read anything, write its feedback, run the repository's tools through uv
ALLOWED_TOOLS = ["Read", "Glob", "Grep", "Write", "Edit", "Bash(uv run *)", "PowerShell(uv run *)"]
DEFAULTS = {"max_agents": 2, "model": "sonnet", "claude": None, "agent_cmd": None, "allowed_tools": ALLOWED_TOOLS,
            "s3_root": "s3://data-interns/nathan.reilly/transfer-qc", "s3_endpoint": None, "aws": "aws",
            "timeout_min": 240, "max_passes": 6}


def settings(**over):
    s = dict(DEFAULTS, **config.section("qc"))
    s.update({k: v for k, v in over.items() if v is not None})
    return s


def round_name(rnd):
    return "round-%02d" % int(rnd)


def round_dir(game, rnd):
    return os.path.join(ROOT, game, round_name(rnd))


def feedback_dir(game, rnd):
    return os.path.join(round_dir(game, rnd), "feedback")


def _now():
    return datetime.datetime.now().isoformat(timespec="seconds")


# --- state ------------------------------------------------------------------------------------
@contextlib.contextmanager
def _locked():
    """The state file is changed by `run` and by `pull` in another terminal: one at a time."""
    os.makedirs(ROOT, exist_ok=True)
    lock = STATE + ".lock"
    t0 = time.time()
    while True:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            if time.time() - t0 > 30:      # a lock left by a process that died
                os.remove(lock)
                continue
            time.sleep(0.1)
    try:
        yield
    finally:
        os.close(fd)
        os.remove(lock)


def load_state():
    return read_json(STATE) if os.path.exists(STATE) else {"games": {}}


def _update(game, **values):
    with _locked():
        st = load_state()
        g = st.setdefault("games", {}).setdefault(game, {})
        g.update(values)
        write_json(STATE, st)
        return g


def game_state(game):
    return load_state().get("games", {}).get(game, {})


def enqueue(game, rnd, force=False, redo=False):
    """Queues a game's round. redo: the round's feedback so far is moved aside (feedback.tryN) and
    the ids it gave out are given again, so a review done over keeps the game's ids continuous."""
    cur = game_state(game)
    if cur.get("state") == "reviewing" and not force:
        raise SystemExit("%s is being reviewed (round %s); a game is in one state at a time" % (game, cur.get("round")))
    fb = feedback_dir(game, rnd)
    if os.path.exists(os.path.join(fb, "findings.json")):
        if not redo:
            raise SystemExit("%s %s has findings already: --redo to review it again" % (game, round_name(rnd)))
        n = 1
        while os.path.exists("%s.try%d" % (fb, n)):
            n += 1
        os.rename(fb, "%s.try%d" % (fb, n))
        first = (cur.get("first_id") or {}).get(str(int(rnd)))
        if first:
            _update(game, next_id=int(first))
    return _update(game, state="queued", round=int(rnd), queued_at=_now(), note=None)


def queue():
    """The games waiting for a reviewer, first in first out."""
    games = load_state().get("games", {})
    return sorted((g for g, v in games.items() if v.get("state") == "queued"), key=lambda g: games[g].get("queued_at", ""))


# --- transfers --------------------------------------------------------------------------------
def _aws(s, *args):
    cmd = [s["aws"]] + list(args) + (["--endpoint-url", s["s3_endpoint"]] if s.get("s3_endpoint") else [])
    print("  $ " + " ".join(cmd))
    subprocess.run(cmd, check=True)


def pull(game, rnd, src=None, keep_s3=False, force=False, **over):
    """A round in: from S3 (deleted there once copied, unless keep_s3) or from a folder."""
    s = settings(**over)
    dest = round_dir(game, rnd)
    os.makedirs(dest, exist_ok=True)
    if src:
        shutil.copytree(src, dest, dirs_exist_ok=True)
    else:
        uri = "%s/%s/%s/" % (s["s3_root"].rstrip("/"), game, round_name(rnd))
        _aws(s, "s3", "sync", uri, dest, "--only-show-errors")
        if not keep_s3:
            _aws(s, "s3", "rm", uri, "--recursive", "--only-show-errors")
    man = os.path.join(dest, "manifest.json")
    if not os.path.exists(man):
        print("warning: no manifest.json in %s" % dest)
    else:
        commit = read_json(man).get("commit")
        if commit and subprocess.run(["git", "merge-base", "--is-ancestor", commit, "HEAD"], cwd=REPO,
                                     capture_output=True).returncode != 0:
            print("warning: this checkout does not have the round's commit %s: git pull first (its tools)" % commit)
    enqueue(game, rnd, force=force)
    print("%s %s: %d take(s) in %s; queued (position %d)" % (game, round_name(rnd), len(takes(game, rnd)), dest,
                                                               queue().index(game) + 1))


def push(game, rnd, dest=None, **over):
    """The feedback out: to S3 (or a folder). The game is then in fixes."""
    s = settings(**over)
    src = feedback_dir(game, rnd)
    if not os.path.exists(os.path.join(src, "findings.json")):
        raise SystemExit("no findings in %s: run the review first" % src)
    if dest:
        shutil.copytree(src, os.path.join(dest, game, round_name(rnd), "feedback"), dirs_exist_ok=True)
        where = dest
    else:
        where = "%s/%s/%s/feedback/" % (s["s3_root"].rstrip("/"), game, round_name(rnd))
        _aws(s, "s3", "sync", src, where, "--only-show-errors")     # work/ too: the findings' evidence
    _update(game, state="fixes", pushed_at=_now())
    f = read_json(os.path.join(src, "findings.json"))
    print("%s %s feedback at %s: %s" % (game, round_name(rnd), where, summary(f)))


# --- the reviewer -----------------------------------------------------------------------------
def _claude(s):
    if s.get("claude"):
        return s["claude"]
    found = shutil.which("claude")
    if found:
        return found
    for name in ("claude.exe", "claude"):
        p = os.path.join(os.path.expanduser("~"), ".local", "bin", name)
        if os.path.exists(p):
            return p
    raise SystemExit("no claude command found: set it with capture qc config --claude PATH")


def _agent_env(game, rnd):
    env = dict(os.environ, QC_GAME=game, QC_ROUND=str(int(rnd)), QC_ROUND_DIR=round_dir(game, rnd),
               QC_FEEDBACK_DIR=feedback_dir(game, rnd))
    uv = shutil.which("uv")
    local_bin = os.path.join(os.path.expanduser("~"), ".local", "bin")
    if not uv and os.path.isdir(local_bin):      # the reviewer runs tools with `uv run`
        env["PATH"] = local_bin + os.pathsep + env.get("PATH", "")
    py = os.path.join(os.path.expanduser("~"), ".local", "share", "uv", "python")
    if sys.platform == "win32" and "UV_PYTHON_INSTALL_DIR" not in env and os.path.isdir(py):
        env["UV_PYTHON_INSTALL_DIR"] = py         # as capture.ps1 does on this kind of machine
    return env


def agent_command(game, rnd, s, resume=None):
    """The reviewer's command; resume: a claude session to continue (a further pass)."""
    if s.get("agent_cmd"):
        if sys.platform != "win32":
            return shlex.split(s["agent_cmd"])
        # Windows paths keep their backslashes (posix=False), which leaves the quotes on: drop them
        return [t[1:-1] if len(t) > 1 and t[0] == t[-1] == '"' else t for t in shlex.split(s["agent_cmd"], posix=False)]
    return ([_claude(s), "-p", "--model", s["model"], "--output-format", "json", "--strict-mcp-config",
             "--add-dir", round_dir(game, rnd)] + (["--resume", resume] if resume else []) +
            ["--allowedTools"] + list(s["allowed_tools"]))


def _listing(d):
    """The round's takes and what each holds, for the prompt."""
    lines = []
    for t in sorted(os.listdir(d)):
        p = os.path.join(d, t)
        if not os.path.isdir(p) or t.startswith("feedback"):
            continue
        counts = {}
        for root, _, files in os.walk(p):
            for f in files:
                ext = os.path.splitext(f)[1].lower() or "(none)"
                counts[ext] = counts.get(ext, 0) + 1
        top = sorted(os.listdir(p))
        lines.append("    - %s: %s; top level: %s" % (
            t, ", ".join("%d %s" % (n, e) for e, n in sorted(counts.items())), ", ".join(top[:25]) + (" ..." if len(top) > 25 else "")))
    return "\n".join(lines) or "(no take folders)"


def _previous(game, rnd):
    """The game's last round with findings, and the capturing machine's triage of it if sent."""
    out = []
    for r in range(int(rnd) - 1, 0, -1):
        f = os.path.join(feedback_dir(game, r), "findings.json")
        if os.path.exists(f):
            out.append("  - findings of %s: %s" % (round_name(r), f))
            break
    for name in ("triage.json", "triage.md"):
        t = os.path.join(round_dir(game, rnd), name)
        if os.path.exists(t):
            out.append("  - the capturing machine's triage of them, sent with this round: %s" % t)
    return "\n".join(out) or "  - none: this is the game's first round"


def prompt(game, rnd, s=None):
    s = s or settings()
    d = round_dir(game, rnd)
    man = os.path.join(d, "manifest.json")
    values = {
        "game": game, "round": str(int(rnd)), "round_name": round_name(rnd), "repo": REPO, "round_dir": d,
        "feedback_dir": feedback_dir(game, rnd), "work_dir": os.path.join(feedback_dir(game, rnd), "work"),
        "model": s.get("model") or "", "takes": _listing(d), "previous": _previous(game, rnd),
        "manifest": json.dumps(read_json(man), indent=1) if os.path.exists(man) else "(no manifest.json was sent)",
        "categories": ", ".join(CATEGORIES),
    }
    text = open(PROMPT, encoding="utf-8").read()
    for k, v in values.items():
        text = text.replace("{{%s}}" % k, v)
    return text


CONTINUE = """Your review of {game}, round {round}, is not finished. findings.json's coverage does not yet show
these takes as checked:
{gaps}
Continue now. For each of them do the least the review covers (the evidence tool's output, the
strips, full frames at the first, middle and last clip frames and wherever a metric points, ten
sweep poses, every person followed), add what you find to findings.json, and set coverage[category]
[take] to what you did. Keep findings.json written as you go. Do not stop until every take is
covered in every category; this is pass {n} of at most {max}."""


def _launch(game, rnd, s, text, n, resume=None):
    """One reviewer process: pass n (1: the prompt; 2 on: CONTINUE in the same claude session)."""
    fb = feedback_dir(game, rnd)
    out_path = os.path.join(fb, "agent_output.json" if n == 1 else "agent_output_pass%d.json" % n)
    out = open(out_path, "wb")
    err = open(os.path.join(fb, "agent_stderr.log"), "ab")
    cmd = agent_command(game, rnd, s, resume=resume)
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=out, stderr=err, cwd=REPO, env=_agent_env(game, rnd))
    p.stdin.write(text.encode("utf-8"))
    p.stdin.close()
    _update(game, state="reviewing", passes=n)
    print("%s %s: reviewer pass %d started (%s, pid %d)" % (game, round_name(rnd), n,
                                                             s.get("model") if not s.get("agent_cmd") else cmd[0], p.pid))
    return {"p": p, "rnd": rnd, "t0": time.time(), "out": out, "err": err, "out_path": out_path, "pass": n}


def start(game, rnd, s):
    fb = feedback_dir(game, rnd)
    os.makedirs(os.path.join(fb, "work"), exist_ok=True)
    text = prompt(game, rnd, s)
    with open(os.path.join(fb, "prompt.md"), "w", encoding="utf-8") as f:
        f.write(text)
    _update(game, started_at=_now(), model=s.get("model"))
    return _launch(game, rnd, s, text, 1)


def gaps(game, rnd):
    """What the reviewer's coverage still lacks: {category: [takes]}, or None without findings."""
    f = os.path.join(feedback_dir(game, rnd), "findings.json")
    try:
        return uncovered(read_json(f), takes(game, rnd))
    except (OSError, ValueError):
        return None


def next_pass(game, r, s):
    """Another pass of the same reviewer while its coverage has gaps (claude only: it resumes the
    session), up to max_passes; None when the review is done."""
    if s.get("agent_cmd") or r["pass"] >= int(s.get("max_passes") or 1):
        return None
    g = gaps(game, r["rnd"])
    if not g:
        return None
    try:
        session = read_json(r["out_path"]).get("session_id")
    except (OSError, ValueError):
        session = None
    if not session:
        return None
    text = CONTINUE.format(game=game, round=int(r["rnd"]), n=r["pass"] + 1, max=s["max_passes"],
                           gaps="\n".join("- %s: %s" % (c, ", ".join(t)) for c, t in g.items()))
    nxt = _launch(game, r["rnd"], s, text, r["pass"] + 1, resume=session)
    nxt["t0"] = r["t0"]          # timeout_min counts from the first pass
    return nxt


def finish(game, rnd, code):
    f = os.path.join(feedback_dir(game, rnd), "findings.json")
    if not os.path.exists(f):
        _update(game, state="failed", finished_at=_now(), note="the reviewer wrote no findings.json (exit %s)" % code)
        print("%s %s: FAILED, no findings.json (exit %s); see %s" % (game, round_name(rnd), code, feedback_dir(game, rnd)))
        return None
    try:
        data = report(game, rnd)
    except (ValueError, KeyError) as e:
        _update(game, state="failed", finished_at=_now(), note="findings.json unusable: %s" % e)
        print("%s %s: FAILED, findings.json unusable: %s" % (game, round_name(rnd), e))
        return None
    note = summary(data) + ("; %d problems, see report.md" % len(data["problems"]) if data.get("problems") else "")
    _update(game, state="reviewed", finished_at=_now(), note=note)
    print("%s %s: reviewed, %s; next: capture qc push %s %d" % (game, round_name(rnd), note, game, int(rnd)))
    return data


def run(**over):
    """Reviewers for the queue, first in first out, at most max_agents at once. Games queued while it
    runs (a pull in another terminal) are picked up; it returns when the queue is empty and every
    reviewer has finished."""
    s = settings(**over)
    n = max(1, int(s["max_agents"]))
    running = {}
    while True:
        for g, r in list(running.items()):
            done = _poll(g, r, s)
            if done is not None:
                if done is True:
                    del running[g]
                else:
                    running[g] = done
        waiting = [g for g in queue() if g not in running]
        while waiting and len(running) < n:
            g = waiting.pop(0)
            running[g] = start(g, game_state(g)["round"], s)
        if not running and not waiting:
            break
        time.sleep(5)
    print(status_text())


def _poll(game, r, s):
    """None while the reviewer runs; its next pass when it stopped short; True once finished."""
    p = r["p"]
    late = time.time() - r["t0"] > float(s["timeout_min"]) * 60
    if p.poll() is None and late:
        p.kill()
        p.wait()
    if p.poll() is None:
        return None
    r["out"].close()
    r["err"].close()
    nxt = None if late else next_pass(game, r, s)
    if nxt:
        return nxt
    finish(game, r["rnd"], p.returncode)
    return True


def review(game, rnd, **over):
    s = settings(**over)
    r = start(game, rnd, s)
    while True:
        r["p"].wait()
        done = _poll(game, r, s)
        if done is True:
            return
        r = done


# --- findings ---------------------------------------------------------------------------------
def _extent(f):
    return max(1, len(f.get("cameras") or [])) * max(1, len(f.get("clip_frames") or []))


def takes(game, rnd):
    d = round_dir(game, rnd)
    return [t for t in sorted(os.listdir(d)) if os.path.isdir(os.path.join(d, t)) and not t.startswith("feedback")]


def uncovered(data, take_names):
    """The categories whose coverage note names neither every take nor "all takes": a review that
    stopped short."""
    cov = data.get("coverage") or {}
    out = {}
    for c in CATEGORIES:
        v = cov.get(c)
        if isinstance(v, dict):          # {take: what was done}: a take missing or "not checked" is a gap
            missing = [t for t in take_names
                       if not str(v.get(t, "")).strip() or str(v.get(t, "")).strip().lower().startswith(NOT_DONE)]
        else:                            # free text: every take named, or "all takes"
            text = str(v or "")
            if "all takes" in text.lower() or "every take" in text.lower():
                continue
            missing = [t for t in take_names if t not in text]
        if missing:
            out[c] = missing
    return out


NOT_DONE = ("not checked", "not examined", "not done", "skipped", "todo", "to do", "none", "n/a")


def validate(data, take_names=()):
    problems = []
    for c, missing in uncovered(data, take_names).items():
        problems.append("coverage of %s does not name %d of %d takes" % (c, len(missing), len(take_names)))
    for i, f in enumerate(data.get("findings", [])):
        bad = [c for c in f.get("categories", []) if c not in CATEGORIES]
        if not f.get("categories") or bad:
            problems.append("finding %d: categories %s (allowed: %s)" % (i, f.get("categories"), ", ".join(CATEGORIES)))
        if f.get("confidence") not in (1, 2, 3):
            problems.append("finding %d: confidence %r (1, 2 or 3)" % (i, f.get("confidence")))
        if not f.get("what"):
            problems.append("finding %d: no 'what'" % i)
    return problems


def report(game, rnd):
    """Gives each finding its id (kept across the game's rounds), sorts them by confidence and then by
    how much of the take they touch, and writes report.md beside findings.json."""
    path = os.path.join(feedback_dir(game, rnd), "findings.json")
    data = read_json(path)
    if not isinstance(data.get("findings"), list):
        raise ValueError("no 'findings' list")
    with _locked():
        st = load_state()
        g = st.setdefault("games", {}).setdefault(game, {})
        nxt = int(g.get("next_id", 1))
        g.setdefault("first_id", {}).setdefault(str(int(rnd)), nxt)   # where this round's new ids start
        for f in data["findings"]:
            if f.get("id"):
                continue
            if f.get("previous_id"):
                f["id"], f["status"] = f["previous_id"], "still present"
            else:
                f["id"], f["status"] = "%s-%03d" % (game, nxt), "new"
                nxt += 1
        g["next_id"] = nxt
        write_json(STATE, st)
    data["findings"].sort(key=lambda f: (-int(f.get("confidence") or 0), -_extent(f)))
    data.update(game=game, round=int(rnd), problems=validate(data, takes(game, rnd)))
    write_json(path, data)
    with open(os.path.join(feedback_dir(game, rnd), "report.md"), "w", encoding="utf-8") as fh:
        fh.write(report_md(data))
    return data


def summary(data):
    fs = data.get("findings", [])
    by = {c: sum(1 for f in fs if f.get("confidence") == c) for c in (3, 2, 1)}
    return "%d findings (confidence 3: %d, 2: %d, 1: %d), %d gone, %d requests" % (
        len(fs), by[3], by[2], by[1], len(data.get("gone", [])), len(data.get("requests", [])))


def _finding_md(f):
    where = ", ".join(x for x in [
        "take %s" % f["take"] if f.get("take") else "",
        "cameras %s" % ", ".join(map(str, f["cameras"])) if f.get("cameras") else "",
        "clip frames %s" % ", ".join(map(str, f["clip_frames"])) if f.get("clip_frames") else "",
        "game times %s" % ", ".join(map(str, f["game_times"])) if f.get("game_times") else ""] if x)
    lines = ["### %s (confidence %s, %s)" % (f.get("id"), f.get("confidence"), f.get("status", "new")),
             "", "Categories: %s. %s" % (", ".join(f.get("categories", [])), where), "", f.get("what", "")]
    ev = f.get("evidence") or {}
    for img in ev.get("images", []):
        lines.append("- image: `%s`" % img)
    for run_ in ev.get("tool_runs", []):
        lines.append("- tool: `%s` -> %s" % (run_.get("command", ""), str(run_.get("output", "")).strip()[:600]))
    if ev.get("numbers"):
        lines.append("- numbers: %s" % ev["numbers"])
    if f.get("suspected_cause"):
        lines.append("- suspected cause: %s" % f["suspected_cause"])
    return "\n".join(lines) + "\n"


def report_md(data):
    fs = data.get("findings", [])
    out = ["# QC %s, round %s" % (data.get("game"), data.get("round")), "",
           "Reviewer: %s. %s." % (data.get("reviewer", {}).get("model", "?") if isinstance(data.get("reviewer"), dict) else "?",
                                  summary(data)), "",
           "| category | confidence 3 | 2 | 1 |", "|---|---|---|---|"]
    for c in CATEGORIES:
        mine = [f for f in fs if c in f.get("categories", [])]
        out.append("| %s | %d | %d | %d |" % (c, *[sum(1 for f in mine if f.get("confidence") == k) for k in (3, 2, 1)]))
    if data.get("problems"):
        out += ["", "Problems with this file: " + "; ".join(data["problems"])]
    for c in CATEGORIES:
        mine = [f for f in fs if c in f.get("categories", [])]
        out += ["", "## %s (%d)" % (c, len(mine)), ""]
        out += [_finding_md(f) for f in mine] or ["None found.\n"]
    out += ["", "## Gone since the last round", ""]
    out += ["- %s: %s" % (g.get("previous_id"), g.get("why", "")) for g in data.get("gone", [])] or ["None."]
    out += ["", "## Requests: tools and data the reviewer wished for", ""]
    out += ["- (%s) %s: %s" % (r.get("kind", "?"), r.get("what", ""), r.get("why", "")) for r in data.get("requests", [])] or ["None."]
    cov = data.get("coverage")
    if cov:
        out += ["", "## Coverage", ""]
        for c in CATEGORIES:
            v = cov.get(c)
            if isinstance(v, dict):
                out += ["**%s**" % c, ""] + ["- %s: %s" % (t, d) for t, d in v.items()] + [""]
            elif v:
                out += ["**%s**: %s" % (c, v), ""]
    return "\n".join(out) + "\n"


# --- status -----------------------------------------------------------------------------------
def status_text():
    games = load_state().get("games", {})
    if not games:
        return "no game in the QC loop yet"
    q = queue()
    rows = ["%-10s %-10s %-9s %s" % ("game", "state", "round", "note")]
    for g, v in sorted(games.items()):
        state = v.get("state", "?") + (" #%d" % (q.index(g) + 1) if g in q else "")
        rows.append("%-10s %-10s %-9s %s" % (g, state, round_name(v["round"]) if v.get("round") else "-", v.get("note") or ""))
    return "\n".join(rows)

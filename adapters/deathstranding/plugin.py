"""Talks to capture_ds.asi (adapters/deathstranding/plugin), the in-game half of this adapter: a
command line written to a control file, the status file read back. See the plug-in's source for the
commands; this module only adds sequence numbers, waiting and parsing.

    p = Plugin()
    p.status()                                  # {'state': 'run', 'frame': '1692', 'game_pos': ..., ...}
    p.cmd("hold"); p.wait_frames(10)
    p.step(seconds=1/30, frames=8)              # exact: 2^32 ticks per second, spread evenly
    p.camera(pos, rot_rows, vfov_deg)           # the render camera from now on; p.camera(None) gives it back
"""
import os
import time

from . import paths

TICKS_PER_SECOND = 2 ** 32


def vec(s):
    return [float(v) for v in s.split(",")]


class Plugin:
    def __init__(self, control=None, status=None):
        self.control = control or paths.plugin_control()
        self.status_path = status or paths.plugin_status()
        self.seq = int(time.time() * 10) % 10 ** 8

    def status(self):
        """The status file as a dict, or {} if there is none (the game not started, or no plug-in)."""
        st = {}
        try:
            with open(self.status_path) as f:
                for line in f:
                    if "=" in line:
                        k, v = line.rstrip("\n").split("=", 1)
                        st[k] = v
        except OSError:
            pass
        return st

    def alive(self, within_s=3.0):
        """True if the plug-in wrote its status recently (it does every 250 ms)."""
        try:
            return time.time() - os.path.getmtime(self.status_path) < within_s
        except OSError:
            return False

    def frame(self):
        return int(self.status().get("frame", "0") or 0)

    def cmd(self, text, timeout=5.0):
        """Sends one command and returns the status that acknowledges it."""
        self.seq += 1
        os.makedirs(os.path.dirname(self.control), exist_ok=True)
        tmp = self.control + ".tmp"
        with open(tmp, "w") as f:
            f.write("%d %s\n" % (self.seq, text))
        os.replace(tmp, self.control)
        t0 = time.time()
        while time.time() - t0 < timeout:
            st = self.status()
            if st.get("seq") == str(self.seq):
                return st
            time.sleep(0.005)
        raise TimeoutError("capture_ds did not answer %r within %.0f s" % (text, timeout))

    def wait_frames(self, n, timeout=60.0):
        """Waits until the game has rendered n more frames (frames counted by the plug-in)."""
        f0 = self.frame()
        t0 = time.time()
        while self.frame() < f0 + n:
            if time.time() - t0 > timeout:
                raise TimeoutError("%d frames did not pass within %.0f s" % (n, timeout))
            time.sleep(0.005)

    def hold(self):
        return self.cmd("hold")

    def run(self):
        return self.cmd("run")

    def step(self, seconds, frames=8, force=False, timeout=30.0):
        """Advances game time by exactly `seconds` (rounded to 2^-32 s) spread evenly over `frames`
        frames, then holds again. Returns the ticks given. force: also while the game pauses."""
        ticks = int(round(seconds * TICKS_PER_SECOND))
        self.cmd("step %d %d%s" % (ticks, frames, " force" if force else ""))
        t0 = time.time()
        while True:
            st = self.status()
            if st.get("state") == "hold" and int(st.get("step_left", "1")) <= 0:
                return int(st.get("ticks", "0"))
            if time.time() - t0 > timeout:
                raise TimeoutError("the step did not finish within %.0f s" % timeout)
            time.sleep(0.005)

    def camera(self, pos, rot=None, fov=None):
        """Renders from this camera: pos (x, y, z world, Z up), rot the 3x3 rows right, forward, up,
        fov the vertical field of view in degrees. None gives the game its camera back."""
        if pos is None:
            return self.cmd("cam off")
        flat = [float(v) for row in rot for v in row]
        return self.cmd("cam %.6f %.6f %.6f %s %.6f" % (pos[0], pos[1], pos[2], " ".join("%.8f" % v for v in flat), fov))

    def rendered(self):
        """(position, rotation rows, vertical FOV) the last frame was rendered with."""
        st = self.status()
        r = vec(st["render_rot"])
        return vec(st["render_pos"]), [r[0:3], r[3:6], r[6:9]], float(st["render_fov"])

    def game_camera(self):
        """The game's own camera last frame (before any override)."""
        st = self.status()
        r = vec(st["game_rot"])
        return vec(st["game_pos"]), [r[0:3], r[3:6], r[6:9]], float(st["game_fov"])


def main():
    """python -m adapters.deathstranding.plugin [command ...]: sends each command (e.g. hold,
    "step 143165577 8", run, "cam off") and prints the status; with none, prints the status."""
    import sys
    p = Plugin()
    if not p.alive():
        print("capture_ds.asi is not writing its status (is the game running with it installed?)")
    for c in sys.argv[1:]:
        p.cmd(c)
    for k, v in p.status().items():
        print("%s=%s" % (k, v))


if __name__ == "__main__":
    main()

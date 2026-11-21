"""What a game must provide for capture. One subclass per game, under adapters/<game>/.

Positions and directions are in the game's world frame; the adapter supplies the
conventions (rig_rotation, heading_basis), so nothing else needs to know the game's axes.
A shot (capture/shots.py) carries world-frame pos, right, fwd, up and vfov_deg.

Capabilities are optional features the generic code only uses when listed:
    "obstacles"   obstacles()/remove_obstacles(): moving things near the rig (capture/obstacles.py)
    "raycast"     raycast(): line probes against the static scene, given to rig providers that fit
                  their rig to each location (capture/scene.py, capture/providers.py)
    "snapshot"    snapshot()/restore() of the world state (BACKLOG.md: shot reuse)
"""


class AdapterError(RuntimeError):
    """The game is not in a state to continue (not running, script layer gone, ...)."""


class Adapter:
    name = "base"
    capabilities = frozenset()

    def __init__(self, settings=None):
        self.settings = dict(settings or {})

    # --- lifecycle -------------------------------------------------------------------------
    def ensure_ready(self, restart=True):
        """Make sure the game is running and drivable; restart it if allowed."""
        raise NotImplementedError

    def open(self):
        """Start a control session with the running game."""
        raise NotImplementedError

    def close(self):
        """End the session and leave the game in its normal state. Safe to call twice."""
        raise NotImplementedError

    def render_settings(self):
        """What affects the pictures besides the poses: resolution, post effects, ..."""
        return {}

    # --- conventions -----------------------------------------------------------------------
    def rig_rotation(self, facing_deg):
        """3x3 rotation, rig frame -> world, so the rig's subject faces facing_deg."""
        raise NotImplementedError

    def heading_basis(self, heading_deg):
        """World unit vectors (forward, right, up) for a level view along heading_deg."""
        raise NotImplementedError

    # --- the world ---------------------------------------------------------------------------
    def subject_state(self):
        """{"position": [x, y, z] of the subject's feet, "facing_deg": f, "clock": "HH:MM",
        "title": readable place name or None}"""
        raise NotImplementedError

    def publish_locations(self, locations):
        """Make the saved locations visible in the game (e.g. a scouting overlay). Optional."""

    def place_title(self, position):
        """Readable place name at a world point, or None. Optional."""
        return None

    def go_to(self, position, facing_deg):
        """Move the subject there and wait until the scene around it has loaded."""
        raise NotImplementedError

    def ground_point(self, position):
        """The ground under a position, as a world point."""
        raise NotImplementedError

    def set_clock(self, hhmm):
        """Set the time of day and let the lighting settle. Returns the time set."""
        raise NotImplementedError

    def hide_subject(self, hidden):
        raise NotImplementedError

    def view(self, pos, fwd, up, vfov_deg, path):
        """Capture one picture from a pose with the world running (previews)."""
        raise NotImplementedError

    # --- frozen capture ----------------------------------------------------------------------
    def begin_frozen(self, first_shot):
        """Freeze the world at one instant, ready to capture shots; settle on first_shot."""
        raise NotImplementedError

    def set_camera(self, shot):
        raise NotImplementedError

    def capture(self, path, settle):
        """Wait `settle` (adapter units, e.g. ticks), save the frame to path. Returns
        {"width", "height", "health": {"problems": [...]}, ...anything worth logging}."""
        raise NotImplementedError

    def advance(self, seconds):
        """Advance the frozen world by exactly `seconds` and freeze it again."""
        raise NotImplementedError

    def wait_frames(self, n):
        """Let n rendered frames pass (e.g. after deleting something, before capturing)."""

    def instant(self):
        """A value that changes whenever the frozen world moves (e.g. the game timer)."""
        raise NotImplementedError

    def health(self):
        """{"problems": [...]} for the current state: focus, subject visible, paused, ..."""
        raise NotImplementedError

    def recover(self):
        """Try to fix what health() reported, without moving the frozen world. True if fixed."""
        return False

    def end_frozen(self):
        raise NotImplementedError

    # --- optional ----------------------------------------------------------------------------
    def obstacles(self, center, radius):
        """Moving things (people, animals, vehicles) within radius as oriented boxes:
        [{"id", "kind", "owned", "center", "axes", "half"}] (capture/obstacles.py)."""
        raise NotImplementedError("obstacles is not a capability of %s" % self.name)

    def remove_obstacles(self, ids):
        """Delete obstacles by id (from the last obstacles() call), never script-owned ones.
        {"removed": count, "skipped": [ids not deleted]}"""
        raise NotImplementedError("obstacles is not a capability of %s" % self.name)

    def snapshot(self):
        raise NotImplementedError("snapshot is not a capability of %s" % self.name)

    def restore(self, state):
        raise NotImplementedError("restore is not a capability of %s" % self.name)

    def raycast(self, starts, ends):
        """Line probes from starts to ends (N x 3 each) against the static scene (terrain,
        buildings, objects, foliage; not people, animals, vehicles).
        Returns (hit bool N, points N x 3, normals N x 3)."""
        raise NotImplementedError("raycast is not a capability of %s" % self.name)

"""Client for lua/jobs/cam_session.lua: RDR2's binding of the shared RedLua session client
(adapters/common/redlua.py).

CAPTURES is the folder the game-side scripts and the ReShade add-on exchange files in
(the default written in capture_loader.lua, and ReShade.ini). Frames only pass through it:
callers move them to their own output folder."""
import os

from ..common import redlua
from ..common.redlua import look_at, vec  # noqa: F401  (used by render_camera and the probes)

CAPTURES = os.path.join(os.environ["USERPROFILE"], "Documents", "RDR2Modding", "captures")
HERE = os.path.dirname(os.path.abspath(__file__))
SESSION_JOB = os.path.join(HERE, "lua", "jobs", "cam_session.lua")


def heartbeat_age():
    return redlua.heartbeat_age(CAPTURES)


class CamSession(redlua.Session):
    def __init__(self, job_id=None, idle_s=300, timeout_s=3600):
        super().__init__(CAPTURES, SESSION_JOB, job_id, idle_s, timeout_s)

    def pose(self, pos, pitch, yaw, fov=50.0):
        return self.cmd("pose", "%.6f %.6f %.6f %.6f %.6f %.6f" % (pos[0], pos[1], pos[2], pitch, yaw, fov))

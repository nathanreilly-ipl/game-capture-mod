# Rig providers

Every rig format the capture tool can use is a provider: one Python file with a small contract.
Add a format by adding a file here (and a pull request), or keep it anywhere on your computer and
pass its path, or put its folder on `CAPTURE_RIG_PATH`.

| file | key | what |
|---|---|---|
| `file.py` | `file` | a `camrig/v1` pose file used as it is (`capture submit --rig <file>`) |
| `camrigs.py` | `camrigs` | the camera-rig repository's rigs solved per location (optional, needs that repository) |
| `ring.py` | `ring` | example: a ring of static cameras, shrunk to clear the scene |

```powershell
.\capture.ps1 providers                                            # what is available here
.\capture.ps1 solve --location <id> --provider ring --set count=12 # solve and plot, no take
.\capture.ps1 submit --location <id> --provider ring --set radius_m=5
.\capture.ps1 submit --location <id> --provider C:\my\rigs\dolly.py --set speed=0.5
```

## The contract

```python
KEY = "ring"                 # unique; the CLI and jobs refer to the provider by it
TITLE = "..."
DEFAULTS = {...}             # settings and their defaults; --set key=value overrides
NEEDS_SCENE = True           # False: solve() gets scene=None and no scene is captured

def solve(scene, subject, settings) -> dict:
    """The camrig/v1 rig for this location. Raise capture.providers.Declined(reason) to refuse
    the location (the job fails with the reason, nothing is captured)."""

# optional
def version(settings) -> str            # default: a hash of this file
def available(settings) -> (bool, str)  # can it run on this machine? (e.g. an external repository)
def freeze(settings, store) -> dict     # at submit: make settings self-contained (copy files into store)
def qc(package_dir, rig, take) -> dict  # after packaging: {"ok": True/False/None, "message": ...}
```

- **scene** (`capture.providers.Scene`): the scene around the location in the rig frame (metres,
  +Y up, the location's ground at y = 0, the subject at the origin facing +Z):
  `triangles` (N x 3 x 3, small patches on every surface the rays hit), `points` and `normals`
  (the ray hits), `name`. Captured with rays by the game adapter (`capture/scene.py`).
- **subject**: `{"height_m", "radius_m", "frames", "fps"}`, a stand-in box for the subject
  (default: the demo performer of the camera-rig repository).
- **settings**: `DEFAULTS` overridden by the job's `--set` values.
- **Output**: a `camrig/v1` rig (the camera-rig repository's `docs/SCHEMA.md`: cameras with
  intrinsics, a `time` mode, OpenCV camera-to-world poses in the rig frame). Everything after
  this, placement, the shot list, capture and packaging, only sees this.
- **qc** runs after packaging; its result goes into the job result and `take.json`. A failed
  check flags the job, or fails it with `--qc fail`.

A job records the provider's key, version and settings. Workers find the provider by key (a
provider file from outside this repository is copied into the queue at submit, so other
machines use the same file) and refuse a job whose provider version differs from theirs.

"""The capture look of Kingdom Come: Deliverance: the game's highest setting of everything that
makes the picture, without the effects a real camera pair would not share. Applied through the
console (our script's `cvar`), in this order: the spec groups first, since each one sets its own
console variables again (sys_spec_PostProcessing turns motion blur back on), then the rest.

The game starts at High (3) whatever its options file or user.cfg say (see adapter.py, The look), so
launch.py sets this at the main menu, before a save loads, and the session sets it again when it
opens (nothing changes then) and reads it back. A change of r_Supersampling resets the eye (a held
frame went from 89.6 to 248 of 255 and stayed there): it must happen while the world runs, and the
ghost run before a hold (eye at speed 30) adapts the eye again.
"""
SPEC = ["sys_spec_GameEffects", "sys_spec_ObjectDetail", "sys_spec_Particles", "sys_spec_Physics", "sys_spec_PostProcessing",
        "sys_spec_Shading", "sys_spec_Shadows", "sys_spec_Texture", "sys_spec_Vegetation", "sys_spec_VolumetricEffects",
        "sys_spec_Water", "sys_spec_light"]
TOP = 7     # the spec groups' top level: Engine\Config\ultraspec.cfg (veryhighspec.cfg is 4)

VISUAL = dict(
    [("sys_spec_Full", TOP)] + [(k, TOP) for k in SPEC],
    r_AntialiasingMode=3,             # SMAA 2TX, the best of the game's anti-aliasing modes
    # 3x3 supersampling: 7680x4320 rendered for 2560x1440. Edge energy (mean |Laplacian| / mean) at one
    # held view, Rattay, 2026-11-25 (probes/supersampling_probe.py): 0.48 at 1x1, 0.31-0.33 at 2x2,
    # 0.30 at 3x3; 166, 106 and 61 frames/s (a shot's 22 frames: 0.13, 0.21, 0.36 s). Foliage loses
    # its stair-steps at 2x2 and is a little cleaner again at 3x3.
    r_Supersampling=3,
    r_TexMaxAnisotropy=16, r_TexMinAnisotropy=16,
    e_ShadowsMaxTexRes=4096,
    r_TexturesStreamPoolSize=8192,    # MB; level 7 sets 4096
    e_LodRatio=100, e_ViewDistRatio=125, e_ViewDistRatioVegetation=100, e_MergedMeshesViewDistRatio=100,
    e_ViewDistRatioDetail=100,
    r_VSync=0,
    # lens effects and what differs from camera to camera: off
    r_MotionBlur=0, r_DepthOfField=0, r_HDRVignetting=0, r_HDRGrainAmount=0, r_ChromaticAberration=0, r_flares=0,
)


def apply(sess, look=None):
    """Sets the look and returns what the game reads back for each, and the ones it did not take."""
    look = VISUAL if look is None else look
    for k, v in look.items():
        sess.cmd("cvar", k, v)
    got = {k: (sess.cmd("cvar", k).data or ["?"])[0] for k in look}
    wrong = {}
    for k, v in got.items():
        try:
            if float(v) != float(look[k]):
                wrong[k] = v
        except ValueError:
            wrong[k] = v
    return got, wrong

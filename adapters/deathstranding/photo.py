"""Death Stranding's photo mode, driven by keys: the game's own pause, with Sam, the HUD and the
game's signs and scan hidden. Takes run inside it from start to end (switching a photo mode in a
held world reset poses and cloth in The Witcher 3, AGENTS.md section 7), with our plug-in's camera
replacing photo mode's (its range around Sam does not apply to ours) and our plug-in's steps
advancing time through photo mode's pause (`step ... force`).

Photo mode's menu, 2026-11-25 (1.004): F8 opens it on the Camera tab (Focal Length, Roll, Show UI,
Show Signs, Show Odradek Scan); Alt switches between camera controls and menu controls; in menu
controls Q/E change tab (Camera, Sam, BB, Depth of Field, Brightness and Filter, Lens Effect,
Frame) and the arrows move and change values; a middle click hides the menu; Esc leaves photo
mode. A value's leftmost choice is Off for each switch used here, so Left always lands on Off
whatever it was. The defaults are what captures need (depth of field, vignette, lens distortion,
chromatic aberration, colour filter and frame all off, exposure 0, contrast 1); game_settings.cfg's
PhotoModeKeepParams 1 (install.py) keeps the choices between photo-mode sessions and leaving does
not ask to confirm discarding them.

Plausibility (AGENTS.md section 1): Show Signs off hides the game's structures and signs left by
players, Show Odradek Scan off its scan markers. The light beams over lost cargo and the chiral
growths are not affected by either (to be checked per place)."""
import time

from ..common import window

F8 = 0x42       # scan code
ALT_VK = 0x12


def _key(h, key, wait=0.35):
    window.focus(h)
    window.press(h, key)
    time.sleep(wait)


def _middle_click(h):
    window.middle_click(h)
    time.sleep(0.5)


def game_paused(p, wait_s=0.6):
    """True if the game's clock stands still with our plug-in letting it run: photo mode, the
    pause menu or a loading screen. Leaves the plug-in in run."""
    p.run()
    t0 = p.status().get("timer0", "0,0").split(",")[0]
    time.sleep(wait_s)
    return p.status().get("timer0", "0,0").split(",")[0] == t0


def open_clean(h, p, log=print):
    """Opens photo mode and sets Show Sam, Show Signs and Show Odradek Scan off, then hides its
    menu. The game pauses (its own pause); call with the world running (no menu open)."""
    if game_paused(p):
        raise RuntimeError("the game is paused already (a menu or photo mode is open)")
    _key(h, F8, wait=2.5)                   # photo mode, Camera tab, camera controls
    if not game_paused(p):
        raise RuntimeError("photo mode did not open (F8)")
    window.focus(h)
    window.press_vk(h, ALT_VK)              # menu controls
    time.sleep(0.6)
    for k in ("Down", "Down", "Down"):      # Focal Length -> Roll -> Show UI -> Show Signs
        _key(h, k)
    _key(h, "Left")                         # Show Signs: Off
    _key(h, "Down")
    _key(h, "Left")                         # Show Odradek Scan: Off
    _key(h, "E", wait=0.8)                  # the Sam tab, Show Sam selected
    _key(h, "Left")                         # Show Sam: Off
    _key(h, "Q", wait=0.8)                  # back to the Camera tab
    window.focus(h)
    window.press_vk(h, ALT_VK)              # camera controls
    time.sleep(0.5)
    _middle_click(h)                        # hide the menu
    log("photo mode on: Sam, signs, scan and menu hidden")


def close(h, p, log=print):
    """Leaves photo mode: Esc shows a hidden menu again, Esc on a shown menu leaves. Checks the
    game runs between presses, so a press never reaches the world (where Esc opens the pause menu)."""
    for _ in range(3):
        if not game_paused(p):
            log("photo mode off")
            return True
        _key(h, "Esc", wait=1.2)
    return not game_paused(p)

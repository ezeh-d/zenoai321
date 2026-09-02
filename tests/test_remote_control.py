"""Owner-only remote pointer control -- the security-critical logic, verified
with a fake pyautogui backend (no real cursor moves)."""

from __future__ import annotations

from reyes_agent.remote_control import RemoteController, _Backend, VIEW, PANEL, MOUSE


class FakeLib:
    def __init__(self):
        self.calls = []
        self.FAILSAFE = True
    def size(self): return (1920, 1080)
    def moveTo(self, x, y): self.calls.append(("move", x, y))
    def click(self, x, y): self.calls.append(("click", x, y))
    def doubleClick(self, x, y): self.calls.append(("double", x, y))
    def rightClick(self, x, y): self.calls.append(("right", x, y))
    def mouseDown(self, x, y): self.calls.append(("down", x, y))
    def mouseUp(self, x, y): self.calls.append(("up", x, y))
    def scroll(self, a): self.calls.append(("scroll", a))


def _ctl():
    lib = FakeLib()
    return RemoteController(backend=_Backend(impl=lib)), lib


# --- modes ------------------------------------------------------------------
def test_default_mode_is_panel_not_mouse():
    ctl, _ = _ctl()
    assert ctl.state()["mode"] == PANEL
    assert ctl.state()["can_move_pointer"] is False


def test_pointer_refused_unless_mouse_mode():
    ctl, lib = _ctl()
    r = ctl.pointer("click", nx=0.5, ny=0.5)
    assert r["ok"] is False and "MOUSE mode" in r["detail"]
    assert lib.calls == []


def test_mouse_mode_moves_and_clicks():
    ctl, lib = _ctl()
    ctl.set_mode(MOUSE)
    assert ctl.pointer("move", nx=0.0, ny=0.0)["ok"]
    assert ctl.pointer("click", nx=1.0, ny=1.0)["ok"]
    assert ("move", 0, 0) in lib.calls
    assert ("click", 1919, 1079) in lib.calls   # normalized -> real screen


# --- coordinate scaling -----------------------------------------------------
def test_coordinates_are_normalized_to_screen():
    ctl, lib = _ctl()
    ctl.set_mode(MOUSE)
    ctl.pointer("move", nx=0.5, ny=0.5)
    assert ("move", 959, 539) in lib.calls        # ~centre of 1920x1080


def test_out_of_range_coordinates_are_clamped():
    ctl, lib = _ctl()
    ctl.set_mode(MOUSE)
    ctl.pointer("move", nx=5.0, ny=-2.0)
    assert ("move", 1919, 0) in lib.calls         # clamped into the screen


# --- emergency stop ---------------------------------------------------------
def test_emergency_stop_refuses_all_pointer_intents():
    ctl, lib = _ctl()
    ctl.set_mode(MOUSE)
    ctl.emergency_stop()
    r = ctl.pointer("click", nx=0.5, ny=0.5)
    assert r["ok"] is False and "disabled" in r["detail"]
    assert lib.calls == []
    assert ctl.state()["mode"] == VIEW and ctl.state()["enabled"] is False


def test_re_enable_after_emergency_stop():
    ctl, _ = _ctl()
    ctl.emergency_stop()
    ctl.enable()
    ctl.set_mode(MOUSE)
    assert ctl.pointer("move", nx=0.1, ny=0.1)["ok"]


# --- keyboard / command actions are never available -------------------------
def test_keyboard_and_command_actions_are_refused():
    ctl, lib = _ctl()
    ctl.set_mode(MOUSE)
    for bad in ("type", "key", "hotkey", "press", "write", "paste", "exec", "run", "command"):
        r = ctl.pointer(bad, nx=0.5, ny=0.5)
        assert r["ok"] is False, bad
    assert lib.calls == []


def test_unknown_action_refused():
    ctl, _ = _ctl()
    ctl.set_mode(MOUSE)
    assert ctl.pointer("teleport", nx=0.5, ny=0.5)["ok"] is False


# --- rate limiting / flood --------------------------------------------------
def test_move_flood_is_coalesced_but_clicks_survive():
    ctl, lib = _ctl()
    ctl.set_mode(MOUSE)
    dropped = 0
    for _ in range(400):
        if ctl.pointer("move", nx=0.5, ny=0.5).get("coalesced"):
            dropped += 1
    # a click after the flood must still go through (never dropped)
    assert ctl.pointer("click", nx=0.5, ny=0.5)["ok"]
    assert dropped > 0                             # the flood was capped
    assert ("click", 959, 539) in lib.calls


def test_scroll_only_in_mouse_mode():
    ctl, lib = _ctl()
    r = ctl.pointer("scroll", amount=3)
    assert r["ok"] is False
    ctl.set_mode(MOUSE)
    assert ctl.pointer("scroll", amount=3)["ok"]
    assert ("scroll", 3) in lib.calls

"""Exercise the real MQTT callback without a broker or running main's loop."""
import ast
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock


SOURCE = Path(__file__).resolve().parents[1] / "svt_light_controller" / "svtlc.py"


class SleepReboundTest(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("svtlc_test", SOURCE)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.ns = vars(module)
        self.client = Mock()
        self.cid = "svtlc_main_bathroom"
        self.bulb = "light.left"
        self.other = "light.right"
        self.config = {"unique_id": "main_bathroom", "mode": "Sleep",
                       "transition": {"enabled": True, "seconds": 1.5}}
        self.ns.update(
            client=self.client, logger=Mock(),
            last_inputs={self.cid: self.states("off")},
            last_output={self.cid: {"state": "off"}},
            last_mode_state={self.cid: {"mode": "Sleep"}},
            last_sleep_state={}, last_circadian_settings={},
            _load_controller_cache=lambda: ([self.config], {}),
            _publish_circadian_targets=Mock(return_value=(None,) * 6),
        )
        # These closures contain the production callback and Sleep behavior.
        # Lift them into a controlled namespace instead of opening connections.
        tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
        main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
        names = {"on_message", "_handle_sleep_mode", "_apply_sleep_targets",
                 "_build_sleep_output_payload", "_scale_brightness", "_scale_color_temp",
                 "_get_curve_range"}
        functions = [n for n in main.body if isinstance(n, ast.FunctionDef) and n.name in names]
        exec(compile(ast.Module(body=functions, type_ignores=[]), str(SOURCE), "exec"), self.ns)

    def states(self, state, other="off"):
        return {key: {"state": value, "brightness": 28 if value == "on" else None,
                      "supported_color_modes": ["xy", "color_temp"],
                      "color_mode": "xy", "hs_color": [0, 100]}
                for key, value in [(self.bulb, state), (self.other, other)]}

    def deliver(self, states):
        self.ns["on_message"](self.client, None, SimpleNamespace(
            topic=f"svtlc/{self.cid}/inputs", retain=False,
            payload=json.dumps({"states": states}).encode()))

    def commands(self):
        return [json.loads(c.args[1]) for c in self.client.publish.call_args_list
                if c.args[0] == f"svtlc/{self.cid}/command"]

    def test_repeated_rebound_never_reapplies_sleep(self):
        self.ns["LAST_OFF_COMMAND"][self.cid] = {self.bulb: self.ns["time"].time()}
        for _ in range(4):
            self.deliver(self.states("on"))
            self.deliver(self.states("off"))
        self.assertEqual(len(self.commands()), 4)
        self.assertTrue(all(c["command"] == "turn_off_inputs" for c in self.commands()))
        self.assertEqual(self.ns["last_inputs"][self.cid][self.bulb]["state"], "off")
        self.assertEqual(self.ns["last_output"][self.cid]["state"], "off")

    def test_normal_on_still_applies_sleep(self):
        self.deliver(self.states("on"))
        self.assertTrue(any(c["command"] == "set_color_inputs" for c in self.commands()))
        self.assertEqual(self.ns["last_output"][self.cid]["state"], "on")

    def test_other_light_can_turn_on_during_rebound(self):
        self.ns["LAST_OFF_COMMAND"][self.cid] = {self.bulb: self.ns["time"].time()}
        self.deliver(self.states("on", "on"))
        on_commands = [c for c in self.commands() if c["command"] != "turn_off_inputs"]
        self.assertTrue(on_commands)
        self.assertTrue(all(self.bulb not in c["targets"] for c in on_commands))
        self.assertEqual(self.ns["last_output"][self.cid]["state"], "on")


if __name__ == "__main__":
    unittest.main()

"""Pre-off must never activate an off or unknown light."""
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch


class PreOffTest(unittest.TestCase):
    def setUp(self):
        source = Path(__file__).resolve().parents[1] / "svt_light_controller" / "svtlc.py"
        spec = importlib.util.spec_from_file_location("svtlc_pre_off_test", source)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.client = Mock()
        self.config = {"pre_off": {"enabled": True},
                       "transition": {"enabled": True, "seconds": 1.5}}

    def run_off(self, states):
        self.client.reset_mock()
        with patch.object(self.module.time, "sleep") as sleep:
            self.module._publish_turn_off_with_pre_stage(
                self.client, "svtlc_restroom", self.config, states,
                ["light.one", "light.two"])
        return [json.loads(c.args[1]) for c in self.client.publish.call_args_list], sleep

    def test_off_or_unknown_lights_receive_only_off(self):
        for states in ({}, None, {"light.one": {"state": "off"}, "light.two": {"state": "off"}},
                       {"light.one": {"state": "unavailable"}, "light.two": {"state": "unknown"}}):
            with self.subTest(states=states):
                commands, sleep = self.run_off(states)
                self.assertEqual([c["command"] for c in commands], ["turn_off_inputs"])
                self.assertEqual(commands[0]["targets"], ["light.one", "light.two"])
                sleep.assert_not_called()

    def test_mixed_group_only_dims_on_target(self):
        commands, sleep = self.run_off({"light.one": {"state": "on"}, "light.two": {"state": "off"},
                                       "light.unrelated": {"state": "on"}})
        self.assertEqual([c["command"] for c in commands], ["set_color_inputs", "turn_off_inputs"])
        self.assertEqual(commands[0]["targets"], ["light.one"])
        self.assertEqual(commands[1]["targets"], ["light.one", "light.two"])
        self.assertEqual(commands[0]["transition"], 1.5)
        sleep.assert_called_once()

    def test_disabled_pre_off_sends_only_off(self):
        self.config["pre_off"]["enabled"] = False
        commands, sleep = self.run_off({"light.one": {"state": "on"}})
        self.assertEqual([c["command"] for c in commands], ["turn_off_inputs"])
        sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()

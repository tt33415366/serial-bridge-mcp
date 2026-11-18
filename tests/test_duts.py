import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from serial_bridge.config import Config, load_config, persist_slots


def _dut(name, title, slots):
    return {"name": name, "title": title, "slots": slots}


def _slot(name, title, com, baud=115200):
    return {"name": name, "title": title, "com": com, "baud": baud}


class DutConfigTest(unittest.TestCase):
    def test_legacy_slots_file_loads_as_one_dut_named_dut(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "serial_bridge.json"
            path.write_text(
                json.dumps(
                    {
                        "slots": [
                            _slot("linux", "Linux", "COM3"),
                            _slot("rtos", "RTOS", "COM6"),
                        ]
                    }
                ),
                encoding="utf-8",
            )

            loaded = load_config(environ={}, config_path=path)

        self.assertEqual("dut", loaded.duts[0]["name"])
        self.assertEqual("DUT", loaded.duts[0]["title"])
        self.assertEqual(
            ["linux", "rtos"],
            [slot["name"] for slot in loaded.duts[0]["slots"]],
        )

    def test_two_duts_may_each_have_a_linux_target(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "serial_bridge.json"
            path.write_text(
                json.dumps(
                    {
                        "duts": [
                            _dut(
                                "alpha",
                                "Alpha",
                                [_slot("linux", "Linux", "COM3"), _slot("rtos", "RTOS", "COM4")],
                            ),
                            _dut(
                                "beta",
                                "Beta",
                                [_slot("linux", "Linux", "COM5"), _slot("rtos", "RTOS", "COM6")],
                            ),
                        ]
                    }
                ),
                encoding="utf-8",
            )

            loaded = load_config(environ={}, config_path=path)

        self.assertEqual(["alpha", "beta"], [dut["name"] for dut in loaded.duts])
        self.assertEqual("COM5", loaded.duts[1]["slots"][0]["com"])
        self.assertIsNone(loaded.warning)

    def test_duplicate_com_across_duts_falls_back_with_warning(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "serial_bridge.json"
            path.write_text(
                json.dumps(
                    {
                        "duts": [
                            _dut("alpha", "Alpha", [_slot("linux", "Linux", "COM3")]),
                            _dut("beta", "Beta", [_slot("linux", "Linux", "COM3")]),
                        ]
                    }
                ),
                encoding="utf-8",
            )

            loaded = load_config(environ={}, config_path=path)

        self.assertIn("COM port", loaded.warning or "")
        self.assertEqual(["dut"], [dut["name"] for dut in loaded.duts])

    def test_duplicate_target_name_inside_one_dut_falls_back_with_warning(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "serial_bridge.json"
            path.write_text(
                json.dumps(
                    {
                        "duts": [
                            _dut(
                                "alpha",
                                "Alpha",
                                [_slot("linux", "Linux", "COM3"), _slot("linux", "Linux 2", "COM4")],
                            )
                        ]
                    }
                ),
                encoding="utf-8",
            )

            loaded = load_config(environ={}, config_path=path)

        self.assertIn("Target Names", loaded.warning or "")
        self.assertEqual(["dut"], [dut["name"] for dut in loaded.duts])

    def test_env_baud_fills_a_gap_on_the_first_dut_only(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "serial_bridge.json"
            path.write_text(
                json.dumps(
                    {
                        "duts": [
                            _dut(
                                "alpha",
                                "Alpha",
                                [
                                    _slot("linux", "Linux", "COM3"),
                                    {"name": "rtos", "title": "RTOS", "com": "COM4"},
                                ],
                            ),
                            _dut(
                                "beta",
                                "Beta",
                                [
                                    _slot("linux", "Linux", "COM5"),
                                    {"name": "rtos", "title": "RTOS", "com": "COM6"},
                                ],
                            ),
                        ]
                    }
                ),
                encoding="utf-8",
            )

            loaded = load_config(
                environ={"SERIAL_BRIDGE_RTOS_BAUD": "230400"},
                config_path=path,
            )

        self.assertEqual(230400, loaded.duts[0]["slots"][1]["baud"])
        self.assertEqual(115200, loaded.duts[1]["slots"][1]["baud"])

    def test_persist_slots_records_every_dut(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "serial_bridge.json"
            config = Config(
                slots=[_slot("linux", "Linux", "COM3")],
                path=path,
                duts=[
                    _dut("alpha", "Alpha", [_slot("linux", "Linux", "COM3")]),
                    _dut("beta", "Beta", [_slot("linux", "Linux", "COM5")]),
                ],
            )

            persist_slots(config, [_slot("linux", "Linux", "COM9")])
            saved = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual("COM9", saved["duts"][0]["slots"][0]["com"])
        self.assertEqual("beta", saved["duts"][1]["name"])
        self.assertEqual("COM5", saved["duts"][1]["slots"][0]["com"])


class DutModeTest(unittest.TestCase):
    def test_starting_one_dut_does_not_open_the_other(self):
        import serial_bridge.hub as hub_module
        from serial_bridge.hub import Hub

        class FakeWorker:
            instances: list[FakeWorker] = []

            def __init__(self, name, port, baud, hub_ref):
                self.name = name
                self.port = port
                self.baud = baud
                self.hub = hub_ref
                self.is_open = False
                self.is_busy = False
                self.__class__.instances.append(self)

            def open(self):
                self.is_open = True

            def start(self):
                pass

            def close(self):
                self.is_open = False

            def abort_agent_work(self):
                pass

        with tempfile.TemporaryDirectory() as temp_dir:
            live = Path(temp_dir)
            config = Config(
                slots=[_slot("linux", "Linux", "COM3")],
                path=live / "serial_bridge.json",
                live_dir=live,
                duts=[
                    _dut(
                        "alpha",
                        "Alpha",
                        [_slot("linux", "Linux", "COM3"), _slot("rtos", "RTOS", "COM4")],
                    ),
                    _dut(
                        "beta",
                        "Beta",
                        [_slot("linux", "Linux", "COM5"), _slot("rtos", "RTOS", "COM6")],
                    ),
                ],
            )
            with mock.patch.object(hub_module, "PortWorker", FakeWorker):
                hub = Hub(config)
                result = hub.start_bridge("alpha")

        self.assertTrue(result["ok"])
        opened = {worker.port for worker in FakeWorker.instances if worker.is_open}
        self.assertEqual({"COM3", "COM4"}, opened)
        modes = {dut["name"]: dut["mode"] for dut in hub.status()["duts"]}
        self.assertEqual({"alpha": "bridge", "beta": "crt"}, modes)

    def test_second_dut_session_log_name_has_no_slash(self):
        import serial_bridge.hub as hub_module
        from serial_bridge.hub import Hub

        class FakeWorker:
            def __init__(self, name, port, baud, hub_ref):
                self.name = name
                self.port = port
                self.is_open = False
                self.is_busy = False

            def open(self):
                self.is_open = True

            def start(self):
                pass

            def close(self):
                self.is_open = False

            def abort_agent_work(self):
                pass

        with tempfile.TemporaryDirectory() as temp_dir:
            live = Path(temp_dir)
            config = Config(
                slots=[_slot("linux", "Linux", "COM3")],
                path=live / "serial_bridge.json",
                live_dir=live,
                duts=[
                    _dut("alpha", "Alpha", [_slot("linux", "Linux", "COM3")]),
                    _dut("beta", "Beta", [_slot("linux", "Linux", "COM5")]),
                ],
            )
            with mock.patch.object(hub_module, "PortWorker", FakeWorker):
                hub = Hub(config)
                hub.start_bridge("beta")
            names = sorted(path.name for path in live.glob("*.log"))

        self.assertEqual(1, len(names))
        self.assertTrue(names[0].startswith("beta-linux-"))
        self.assertFalse((live / "beta").exists())


class DutUiMarkupTest(unittest.TestCase):
    ROOT = Path(__file__).resolve().parent.parent

    def test_add_dut_panel_has_its_own_scan_button(self):
        html = (self.ROOT / "static" / "index.html").read_text(encoding="utf-8")
        start = html.index('id="add-dut-panel"')
        panel = html[start : html.index("</form>", start)]

        self.assertIn('id="btn-add-dut-scan"', panel)

    def test_strip_has_add_dut_and_no_manager_dialog(self):
        html = (self.ROOT / "static" / "index.html").read_text(encoding="utf-8")
        strip = html[html.index('id="dut-bar"') : html.index("</nav>")]

        self.assertIn('id="btn-add-dut"', strip)
        self.assertNotIn("dut-manager", html)
        self.assertNotIn("btn-manage-duts", html)

    def test_main_column_does_not_depend_on_child_count(self):
        css = (self.ROOT / "static" / "style.css").read_text(encoding="utf-8")
        start = css.index(".main {")
        rule = css[start : css.index("}", start)]

        self.assertNotIn("grid-template-rows", rule)
        self.assertIn("flex-direction: column", rule)
        self.assertRegex(css, r"\.main > main\s*\{[^}]*flex:\s*1 1 0")


class DutEntranceTest(unittest.TestCase):
    def test_http_can_add_a_dut_and_bridge_only_that_one(self):
        import serial_bridge.app as app_module
        import serial_bridge.hub as hub_module
        from fastapi.testclient import TestClient
        from serial_bridge.hub import Hub

        class FakeWorker:
            instances: list[FakeWorker] = []

            def __init__(self, name, port, baud, hub_ref):
                self.port = port
                self.is_open = False
                self.is_busy = False
                self.__class__.instances.append(self)

            def open(self):
                self.is_open = True

            def start(self):
                pass

            def close(self):
                self.is_open = False

            def abort_agent_work(self):
                pass

        with tempfile.TemporaryDirectory() as temp_dir:
            live = Path(temp_dir)
            config = Config(
                slots=[_slot("linux", "Linux", "COM3"), _slot("rtos", "RTOS", "COM4")],
                path=live / "serial_bridge.json",
                live_dir=live,
                duts=[
                    _dut(
                        "alpha",
                        "Alpha",
                        [_slot("linux", "Linux", "COM3"), _slot("rtos", "RTOS", "COM4")],
                    )
                ],
            )
            with mock.patch.object(hub_module, "PortWorker", FakeWorker):
                hub = Hub(config)
                client = TestClient(app_module.app, client=("127.0.0.1", 50000))
                with mock.patch.object(app_module, "hub", hub):
                    created = client.post(
                        "/api/duts",
                        json={
                            "name": "beta",
                            "title": "Beta",
                            "slots": [
                                _slot("linux", "Linux", "COM5"),
                                _slot("rtos", "RTOS", "COM6"),
                            ],
                        },
                    )
                    switched = client.post(
                        "/api/mode",
                        json={"mode": "bridge", "dut": "beta"},
                    )

        self.assertEqual(200, created.status_code)
        self.assertTrue(created.json()["ok"])
        self.assertEqual(
            ["alpha", "beta"],
            [dut["name"] for dut in created.json()["duts"]],
        )
        self.assertTrue(switched.json()["ok"])
        opened = {worker.port for worker in FakeWorker.instances if worker.is_open}
        self.assertEqual({"COM5", "COM6"}, opened)
        modes = {dut["name"]: dut["mode"] for dut in hub.status()["duts"]}
        self.assertEqual({"alpha": "crt", "beta": "bridge"}, modes)


    def test_http_can_rename_a_dut_title_and_it_persists(self):
        import serial_bridge.app as app_module
        import serial_bridge.hub as hub_module
        from fastapi.testclient import TestClient
        from serial_bridge.hub import Hub

        class FakeWorker:
            def __init__(self, name, port, baud, hub_ref):
                self.port = port
                self.is_open = False
                self.is_busy = False

            def open(self):
                self.is_open = True

            def start(self):
                pass

            def close(self):
                self.is_open = False

            def abort_agent_work(self):
                pass

        with tempfile.TemporaryDirectory() as temp_dir:
            live = Path(temp_dir)
            config = Config(
                slots=[_slot("linux", "Linux", "COM3"), _slot("rtos", "RTOS", "COM4")],
                path=live / "serial_bridge.json",
                live_dir=live,
            )
            with mock.patch.object(hub_module, "PortWorker", FakeWorker):
                hub = Hub(config)
                client = TestClient(app_module.app, client=("127.0.0.1", 50000))
                with mock.patch.object(app_module, "hub", hub):
                    renamed = client.post("/api/duts/dut/title", json={"title": "Board 1"})
                    missing = client.post("/api/duts/nope/title", json={"title": "X"})
            saved = json.loads((live / "serial_bridge.json").read_text(encoding="utf-8"))

        self.assertTrue(renamed.json()["ok"])
        self.assertEqual("Board 1", renamed.json()["duts"][0]["title"])
        self.assertEqual("dut", renamed.json()["duts"][0]["name"])
        self.assertFalse(missing.json()["ok"])
        self.assertEqual("Board 1", saved["duts"][0]["title"])

    def test_binding_update_targets_one_dut_and_ignores_other_duts_mode(self):
        import serial_bridge.hub as hub_module
        from serial_bridge.hub import Hub

        class FakeWorker:
            def __init__(self, name, port, baud, hub_ref):
                self.port = port
                self.is_open = False
                self.is_busy = False

            def open(self):
                self.is_open = True

            def start(self):
                pass

            def close(self):
                self.is_open = False

            def abort_agent_work(self):
                pass

        with tempfile.TemporaryDirectory() as temp_dir:
            live = Path(temp_dir)
            config = Config(
                slots=[_slot("linux", "Linux", "COM3"), _slot("rtos", "RTOS", "COM4")],
                path=live / "serial_bridge.json",
                live_dir=live,
                duts=[
                    _dut("alpha", "Alpha", [_slot("linux", "Linux", "COM3"), _slot("rtos", "RTOS", "COM4")]),
                    _dut("beta", "Beta", [_slot("linux", "Linux", "COM5"), _slot("rtos", "RTOS", "COM6")]),
                ],
            )
            with mock.patch.object(hub_module, "PortWorker", FakeWorker):
                hub = Hub(config)
                self.assertTrue(hub.start_bridge("alpha")["ok"])
                changed = hub.update_slots(
                    [_slot("linux", "Linux", "COM7"), _slot("rtos", "RTOS", "COM6")],
                    None,
                    dut="beta",
                )
                clash = hub.update_slots(
                    [_slot("linux", "Linux", "COM3"), _slot("rtos", "RTOS", "COM6")],
                    None,
                    dut="beta",
                )
                locked = hub.update_slots(
                    [_slot("linux", "Linux", "COM8"), _slot("rtos", "RTOS", "COM4")],
                    None,
                    dut="alpha",
                )
            saved = json.loads((live / "serial_bridge.json").read_text(encoding="utf-8"))

        self.assertTrue(changed["ok"], changed)
        self.assertEqual(["COM7", "COM6"], [s["com"] for s in saved["duts"][1]["slots"]])
        self.assertEqual(["COM3", "COM4"], [s["com"] for s in saved["duts"][0]["slots"]])
        self.assertEqual(4, len(hub.ports))
        self.assertFalse(clash["ok"])
        self.assertIn("COM port", clash["error"])
        self.assertFalse(locked["ok"])
        self.assertIn("CRT", locked["error"])

    def test_http_remove_dut_stops_its_bridge_and_keeps_the_last_dut(self):
        import serial_bridge.app as app_module
        import serial_bridge.hub as hub_module
        from fastapi.testclient import TestClient
        from serial_bridge.hub import Hub

        class FakeWorker:
            instances = []

            def __init__(self, name, port, baud, hub_ref):
                FakeWorker.instances.append(self)
                self.port = port
                self.is_open = False
                self.is_busy = False

            def open(self):
                self.is_open = True

            def start(self):
                pass

            def close(self):
                self.is_open = False

            def abort_agent_work(self):
                pass

        with tempfile.TemporaryDirectory() as temp_dir:
            live = Path(temp_dir)
            config = Config(
                slots=[_slot("linux", "Linux", "COM3"), _slot("rtos", "RTOS", "COM4")],
                path=live / "serial_bridge.json",
                live_dir=live,
                duts=[
                    _dut("alpha", "Alpha", [_slot("linux", "Linux", "COM3"), _slot("rtos", "RTOS", "COM4")]),
                    _dut("beta", "Beta", [_slot("linux", "Linux", "COM5"), _slot("rtos", "RTOS", "COM6")]),
                ],
            )
            with mock.patch.object(hub_module, "PortWorker", FakeWorker):
                hub = Hub(config)
                client = TestClient(app_module.app, client=("127.0.0.1", 50000))
                with mock.patch.object(app_module, "hub", hub):
                    hub.start_bridge("beta")
                    removed = client.delete("/api/duts/beta")
                    last = client.delete("/api/duts/alpha")
            saved = json.loads((live / "serial_bridge.json").read_text(encoding="utf-8"))
            still_open = [w for w in FakeWorker.instances if w.is_open]

        self.assertEqual([], still_open)
        self.assertTrue(removed.json()["ok"])
        self.assertEqual(["alpha"], [d["name"] for d in removed.json()["duts"]])
        self.assertEqual({"linux", "rtos"}, set(hub.ports))
        self.assertFalse(last.json()["ok"])
        self.assertEqual(["alpha"], [d["name"] for d in saved["duts"]])

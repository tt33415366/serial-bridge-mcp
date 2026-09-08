# One or Two Target Slots Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Hub can have one or two Targets; the Operator adds or removes a Slot in CRT Mode, and the absent Target does not exist.

**Architecture:** Persisted `slots[]` length is the count (1 or 2). `load_config` must not pad a one-slot file back onto `DEFAULT_SLOTS`. CRT `update_slots` already persists immediately; teach `_apply_slot_updates` and `SlotPolicy` to accept a length change. The Operator UI keeps two pane slots in the DOM and hides the unused one. Add is one CRT dialog prefilled from `unused_default_slot` / `add_defaults`; Remove asks `confirm` then POSTs the remaining Slot.

**Tech Stack:** Python 3.10, unittest, FastAPI/Pydantic, Ground Station `static/app.js` + Node fake-DOM in `tests/test_ground_station_exec_ui.py`.

## Global Constraints

- Product language: Hub, Target, Target Slot, Target Name, Display Title, Port Binding, Operator, Agent, CRT Mode, Bridge Mode. Never “serial interface” or “bridge process”.
- A Hub has one or two Targets. The absent Target does not exist (`serial_status` / `Hub.ports` / Agent resolve).
- Default remains two Slots (`linux` / `rtos`, COM3/COM6 @ 115200).
- Operator adds or removes Slots only in CRT Mode. Env/CLI never change the count.
- Env/CLI overlay only existing Slots. A Slot 1 override (`SERIAL_BRIDGE_SLOT1_*`, `SERIAL_BRIDGE_RTOS_*`, `--rtos-port`, `--rtos-baud`) with a one-slot file fails startup (raise, do not warn-and-fallback).
- Agents always pass `target`. Do not make `target` optional.
- Add dialog fields: Display Title, COM, baud. Target Name is derived from Title (existing `deriveTargetName`). Defaults = first `DEFAULT_SLOTS` entry whose name is not taken. Cancel or validation failure creates nothing.
- Add/Remove persist immediately via `POST /api/bindings` / `Hub.update_slots`, including the current form values of surviving Slots.
- Remove requires `globalThis.confirm`. Cannot remove the last Target.
- `LINUX_*` / `--linux-*` / `--rtos-*` stay index aliases (Slot 0 / Slot 1).
- Legacy `ports.{linux,rtos}` still migrates to exactly two Slots.
- A removed Target’s Session Log stays on disk.
- Follow `superpowers:test-driven-development`: no production code without a failing test first.
- Do not add N-serial, disabled twins, `--slot-count`, or unique-COM enforcement.

---

### Task 1: One- or two-slot config load and persist

**Files:**
- Modify: `serial_bridge/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `MIN_SLOT_COUNT = 1`, `MAX_SLOT_COUNT = 2` in `serial_bridge/config.py`. Keep `SLOT_COUNT = MAX_SLOT_COUNT` so existing two-slot callers compile until later tasks drop it.
- Produces: `unused_default_slot(slots: Sequence[Mapping[str, object]]) -> dict[str, str | int]` — copy of the first `DEFAULT_SLOTS` entry whose `name` is not in `slots`; raises `ValueError("both default Target Names are already used")` if none remain.
- `_parse_saved_slots` / `_validated_slots` accept `len` in `{1, 2}`; error text: `slots must be an array of 1 or 2 entries`.
- `load_config`: after a successful file parse, `slots` length equals the file’s `slots` length (do not pad from `DEFAULT_SLOTS`). Partial fields of `slots[i]` still merge over the seeded row at that index (`defaults → env/CLI`, then file keys win).
- `persist_slots` writes whatever validated length it was given (1 or 2).
- Consumes: existing `DEFAULT_SLOTS`, `_partial_slot`, `_slot_from_partial`, warning fallback for corrupt/invalid files.

- [ ] **Step 1: Write the failing tests**

Add to `ConfigTest` in `tests/test_config.py`. Import `unused_default_slot`.

```python
    def test_one_slot_file_is_the_count(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "serial_bridge.json"
            config_path.write_text(
                json.dumps(
                    {
                        "slots": [
                            {
                                "name": "rtos",
                                "title": "RTOS",
                                "com": "COM18",
                                "baud": 115200,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            config = load_config(environ={}, config_path=config_path)

            self.assertEqual(1, len(config.slots))
            self.assertEqual("rtos", config.slots[0]["name"])
            self.assertEqual("COM18", config.slots[0]["com"])
            self.assertIsNone(config.warning)

    def test_three_slot_file_falls_back_with_warning(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "serial_bridge.json"
            config_path.write_text(
                json.dumps(
                    {
                        "slots": [
                            {"name": "linux", "title": "Linux", "com": "COM3", "baud": 115200},
                            {"name": "rtos", "title": "RTOS", "com": "COM6", "baud": 115200},
                            {"name": "extra", "title": "Extra", "com": "COM7", "baud": 115200},
                        ]
                    }
                ),
                encoding="utf-8",
            )

            config = load_config(environ={}, config_path=config_path)

            self.assertEqual(2, len(config.slots))
            self.assertIn("Could not load config", config.warning or "")

    def test_persist_slots_accepts_one_slot(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "serial_bridge.json"
            config = Config(slots=list(DEFAULT_SLOTS), path=config_path)
            one = [
                {"name": "linux", "title": "Linux", "com": "COM8", "baud": 57600},
            ]

            saved = persist_slots(config, one)
            raw = json.loads(config_path.read_text(encoding="utf-8"))

        self.assertEqual(1, len(saved))
        self.assertEqual(1, len(raw["slots"]))
        self.assertEqual("COM8", raw["slots"][0]["com"])

    def test_unused_default_slot_prefers_first_free_twin(self):
        linux_only = [{"name": "linux", "title": "Linux", "com": "COM3", "baud": 115200}]
        rtos_only = [{"name": "rtos", "title": "RTOS", "com": "COM6", "baud": 115200}]
        radio = [{"name": "radio", "title": "Radio", "com": "COM6", "baud": 115200}]

        self.assertEqual("rtos", unused_default_slot(linux_only)["name"])
        self.assertEqual("COM6", unused_default_slot(linux_only)["com"])
        self.assertEqual("linux", unused_default_slot(rtos_only)["name"])
        self.assertEqual("COM3", unused_default_slot(radio)["com"])
        with self.assertRaises(ValueError):
            unused_default_slot(list(DEFAULT_SLOTS))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_config.ConfigTest.test_one_slot_file_is_the_count tests.test_config.ConfigTest.test_three_slot_file_falls_back_with_warning tests.test_config.ConfigTest.test_persist_slots_accepts_one_slot tests.test_config.ConfigTest.test_unused_default_slot_prefers_first_free_twin`

Expected: FAIL — one-slot file raises / persist rejects length ≠ 2; `unused_default_slot` is not defined.

- [ ] **Step 3: Write minimal implementation**

In `serial_bridge/config.py`:

```python
MIN_SLOT_COUNT = 1
MAX_SLOT_COUNT = 2
SLOT_COUNT = MAX_SLOT_COUNT

def unused_default_slot(slots: Sequence[Mapping[str, object]]) -> dict[str, str | int]:
    taken = {str(slot["name"]) for slot in slots}
    for default in DEFAULT_SLOTS:
        if default["name"] not in taken:
            return dict(default)
    raise ValueError("both default Target Names are already used")
```

Add `Sequence` to the `typing` import.

Change `_parse_saved_slots` and `_validated_slots` length checks to:

```python
if not isinstance(raw_slots, list) or not (
    MIN_SLOT_COUNT <= len(raw_slots) <= MAX_SLOT_COUNT
):
    raise ValueError("slots must be an array of 1 or 2 entries")
```

In `load_config`, after `saved = _parse_saved_slots(raw)`:

```python
candidate = deepcopy(slots[: len(saved)])
for index, values in enumerate(saved):
    candidate[index].update(values)
```

Do not keep `candidate = deepcopy(slots)` (that is the two-slot pad).

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest tests.test_config.ConfigTest.test_one_slot_file_is_the_count tests.test_config.ConfigTest.test_three_slot_file_falls_back_with_warning tests.test_config.ConfigTest.test_persist_slots_accepts_one_slot tests.test_config.ConfigTest.test_unused_default_slot_prefers_first_free_twin tests.test_config -q`

Expected: PASS (new tests and the rest of `test_config.py`).

- [ ] **Step 5: Commit**

```bash
git add serial_bridge/config.py tests/test_config.py
git commit -m "feat: load and persist one or two Target Slots"
```

---

### Task 2: Slot 1 env/CLI cannot change the count

**Files:**
- Modify: `serial_bridge/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `_slot1_override_source(env: Mapping[str, str], cli_overrides: Mapping[str, Mapping[str, str | int | None]] | None) -> str | None`
  - Env, first hit: `SERIAL_BRIDGE_SLOT1_PORT`, `SERIAL_BRIDGE_SLOT1_BAUD`, `SERIAL_BRIDGE_RTOS_PORT`, `SERIAL_BRIDGE_RTOS_BAUD`.
  - CLI, first hit among non-`None` values: `--rtos-port`, `--rtos-baud`, `--slot1-port`, `--slot1-baud` (keys `rtos` / `slot1` in `cli_overrides`).
- After `load_config` finishes merging a **successful** one-slot file (no `warning`), if `_slot1_override_source` is not `None`, **raise** `ValueError(f"{source} refers to Target Slot 1 but only one Slot is configured")`. Do not turn this into `config.warning` and a two-slot fallback.
- One-slot file + only Slot 0 / `LINUX_*` / `--linux-*` overlays still load (file values win, same as today).
- No file (default two Slots): Slot 1 env/CLI still apply. Unchanged.
- Consumes: Task 1 one-slot file load.

- [ ] **Step 1: Write the failing tests**

```python
    def test_one_slot_file_rejects_rtos_env(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "serial_bridge.json"
            config_path.write_text(
                json.dumps(
                    {
                        "slots": [
                            {
                                "name": "linux",
                                "title": "Linux",
                                "com": "COM8",
                                "baud": 115200,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaises(ValueError) as ctx:
                load_config(
                    environ={"SERIAL_BRIDGE_RTOS_PORT": "COM9"},
                    config_path=config_path,
                )

        self.assertIn("SERIAL_BRIDGE_RTOS_PORT", str(ctx.exception))
        self.assertIn("only one Slot", str(ctx.exception))

    def test_one_slot_file_rejects_rtos_cli(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "serial_bridge.json"
            config_path.write_text(
                json.dumps(
                    {
                        "slots": [
                            {
                                "name": "linux",
                                "title": "Linux",
                                "com": "COM8",
                                "baud": 115200,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaises(ValueError) as ctx:
                load_config_from_args(
                    ["--rtos-port", "COM9"],
                    environ={},
                    config_path=config_path,
                )

        self.assertIn("--rtos-port", str(ctx.exception))

    def test_one_slot_file_allows_linux_env_then_file_wins(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "serial_bridge.json"
            config_path.write_text(
                json.dumps(
                    {
                        "slots": [
                            {
                                "name": "linux",
                                "title": "Linux",
                                "com": "COM30",
                                "baud": 38400,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            config = load_config(
                environ={"SERIAL_BRIDGE_LINUX_PORT": "COM20"},
                config_path=config_path,
            )

            self.assertEqual(1, len(config.slots))
            self.assertEqual("COM30", config.slots[0]["com"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_config.ConfigTest.test_one_slot_file_rejects_rtos_env tests.test_config.ConfigTest.test_one_slot_file_rejects_rtos_cli tests.test_config.ConfigTest.test_one_slot_file_allows_linux_env_then_file_wins`

Expected: FAIL — one-slot + `RTOS` env/CLI currently loads (or warns) instead of raising.

- [ ] **Step 3: Write minimal implementation**

```python
def _slot1_override_source(
    env: Mapping[str, str],
    cli_overrides: Mapping[str, Mapping[str, str | int | None]] | None,
) -> str | None:
    for names in (_ENV_SLOT_NAMES[1], _ENV_ALIASES[1]):
        for key in names.values():
            if key in env:
                return key
    cli = cli_overrides or {}
    for alias, flag_com, flag_baud in (
        ("rtos", "--rtos-port", "--rtos-baud"),
        ("slot1", "--slot1-port", "--slot1-baud"),
    ):
        values = cli.get(alias) or {}
        if values.get("com") is not None:
            return flag_com
        if values.get("baud") is not None:
            return flag_baud
    return None
```

At the end of `load_config`, after the file try/except, before `return Config(...)`:

```python
    if len(slots) == 1:
        source = _slot1_override_source(env, cli_overrides)
        if source is not None:
            raise ValueError(
                f"{source} refers to Target Slot 1 but only one Slot is configured"
            )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest tests.test_config -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add serial_bridge/config.py tests/test_config.py
git commit -m "feat: reject Slot 1 env and CLI when only one Slot exists"
```

---

### Task 3: SlotPolicy treats count change as a CRT Binding edit

**Files:**
- Modify: `serial_bridge/config.py` (`SlotPolicy.decide`)
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: Task 1 length 1–2 lists.
- `SlotPolicy.decide`: if `len(slots)` is not in `[MIN_SLOT_COUNT, MAX_SLOT_COUNT]`, return `SlotDecision(False, False, error="A Hub has one or two Target Slots")` before other checks.
- Length change is not title-only (already true via `len(slots) != len(self._config.slots)`). In Bridge / with workers, that already yields `Port Bindings can only be changed in CRT Mode`. Add an explicit test; do not change that error string.
- In CRT with no workers, length 2→1 and 1→2 are allowed.

- [ ] **Step 1: Write the failing tests**

```python
    def test_slot_policy_rejects_zero_or_three_slots(self):
        config = Config(slots=_default_slots(), path=Path("serial_bridge.json"))
        policy = config_module.SlotPolicy(config)

        empty = policy.decide([], live_dir=None, mode="crt", has_workers=False)
        three = policy.decide(
            _default_slots() + [{"name": "x", "title": "X", "com": "COM7", "baud": 1}],
            live_dir=None,
            mode="crt",
            has_workers=False,
        )

        self.assertFalse(empty.allowed)
        self.assertEqual("A Hub has one or two Target Slots", empty.error)
        self.assertFalse(three.allowed)
        self.assertEqual("A Hub has one or two Target Slots", three.error)

    def test_slot_policy_rejects_count_change_in_bridge_mode(self):
        config = Config(slots=_default_slots(), path=Path("serial_bridge.json"))
        one = [_default_slots()[0]]

        decision = config_module.SlotPolicy(config).decide(
            one, live_dir=None, mode="bridge", has_workers=True
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(
            "Port Bindings can only be changed in CRT Mode", decision.error
        )

    def test_slot_policy_allows_count_change_in_idle_crt_mode(self):
        config = Config(slots=_default_slots(), path=Path("serial_bridge.json"))
        one = [_default_slots()[0]]

        decision = config_module.SlotPolicy(config).decide(
            one, live_dir=None, mode="crt", has_workers=False
        )

        self.assertTrue(decision.allowed)
        self.assertFalse(decision.title_only)
```

`test_slot_policy_allows_count_change_in_idle_crt_mode` may already pass (length mismatch is not title-only). If Step 2 shows it PASS, keep it as a characterization test and still implement the 0/3 rejection from the first test.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_config.ConfigTest.test_slot_policy_rejects_zero_or_three_slots tests.test_config.ConfigTest.test_slot_policy_rejects_count_change_in_bridge_mode tests.test_config.ConfigTest.test_slot_policy_allows_count_change_in_idle_crt_mode`

Expected: `test_slot_policy_rejects_zero_or_three_slots` FAIL (0 slots currently looks like a Binding edit, not the new error). Bridge count-change should already FAIL-allowed with the CRT lock — if it PASSes, it is characterization.

- [ ] **Step 3: Write minimal implementation**

At the top of `SlotPolicy.decide`:

```python
        if not MIN_SLOT_COUNT <= len(slots) <= MAX_SLOT_COUNT:
            return SlotDecision(
                False,
                False,
                error="A Hub has one or two Target Slots",
            )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest tests.test_config -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add serial_bridge/config.py tests/test_config.py
git commit -m "feat: SlotPolicy allows CRT add/remove and rejects 0 or 3 Slots"
```

---

### Task 4: Hub applies add/remove and exposes add_defaults

**Files:**
- Modify: `serial_bridge/hub/core.py`
- Modify: `serial_bridge/hub/mode_transition.py`
- Test: `tests/test_hub.py`

**Interfaces:**
- Consumes: `unused_default_slot`, `MAX_SLOT_COUNT`, `persist_slots`, `SlotPolicy` from Tasks 1–3.
- `_apply_slot_updates(self, slots)` must not index `self.config.slots[index]` when `index >= len(self.config.slots)`.
  - For each new slot, reuse `self.ports[new_name]` if present (keeps Session Log when compacting), else reuse `self.ports[old_name]` when the name at that index is unchanged, else `{"log": None}`.
  - Then `self.ports = new_ports` (dropped names disappear) and `self.config.slots = slots`.
- `Hub.status()` includes `add_defaults`: a copy of `unused_default_slot(self.config.slots)` when `len(self.config.slots) < MAX_SLOT_COUNT`, else omit the key or set `None`.
- `start_bridge` already loops `self._hub.ports`; one Target opens one worker. Change the system line to `Agent and Operator share the stream below` when `len(self._hub.ports) == 1`, else keep `both streams`.
- `make_config` in tests may take a one-slot list via a local helper; do not change production `make_config` unless a test needs it.

- [ ] **Step 1: Write the failing tests**

In `tests/test_hub.py`, add a helper next to `make_config`:

```python
def make_one_slot_config(path=Path("serial_bridge.json"), live_dir=None):
    kwargs = {
        "slots": [
            {"name": "linux", "title": "Linux", "com": "COM3", "baud": 115200},
        ],
        "path": path,
    }
    if live_dir is not None:
        kwargs["live_dir"] = live_dir
    return Config(**kwargs)
```

Add to `HubTest`:

```python
    def test_update_slots_can_drop_to_one_target_in_crt(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            hub = Hub(make_config(Path(temp_dir) / "serial_bridge.json"))
            one = [dict(hub.config.slots[0])]

            result = hub.update_slots(one)

        self.assertTrue(result["ok"])
        self.assertEqual(["linux"], list(hub.ports))
        self.assertNotIn("rtos", hub.status()["ports"])
        self.assertEqual("rtos", hub.status()["add_defaults"]["name"])

    def test_update_slots_can_add_second_target_in_crt(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            hub = Hub(make_one_slot_config(Path(temp_dir) / "serial_bridge.json"))
            two = [
                dict(hub.config.slots[0]),
                {"name": "rtos", "title": "RTOS", "com": "COM6", "baud": 115200},
            ]

            result = hub.update_slots(two)

        self.assertTrue(result["ok"])
        self.assertEqual({"linux", "rtos"}, set(hub.ports))
        self.assertIsNone(hub.status().get("add_defaults"))

    def test_update_slots_keeps_remaining_target_log_when_removing_other(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            hub = Hub(make_config(Path(temp_dir) / "serial_bridge.json"))
            hub.ports["rtos"]["log"] = str(Path(temp_dir) / "rtos-session.log")
            one = [dict(hub.config.slots[1])]

            result = hub.update_slots(one)

        self.assertTrue(result["ok"])
        self.assertEqual(["rtos"], list(hub.ports))
        self.assertEqual(
            str(Path(temp_dir) / "rtos-session.log"),
            hub.ports["rtos"]["log"],
        )

    def test_update_slots_rejects_count_change_in_bridge_mode(self):
        hub = Hub(make_config())
        hub.mode = "bridge"
        hub.workers["linux"] = object()

        result = hub.update_slots([dict(hub.config.slots[0])])

        self.assertFalse(result["ok"])
        self.assertEqual(
            "Port Bindings can only be changed in CRT Mode", result["error"]
        )
        self.assertEqual(2, len(hub.ports))
```

For the Bridge system line, extend `test_bridge_mode_opens_sends_and_releases_both_targets` only if it already asserts the text; otherwise add:

```python
    def test_one_target_bridge_system_line_says_the_stream(self):
        # Same FakePortWorker patch as test_bridge_mode_opens_sends_and_releases_both_targets.
        # Assert the emitted system text uses "the stream" and only one worker opens.
```

Copy the `patch` style from `test_bridge_mode_opens_sends_and_releases_both_targets` in the same file (do not invent a new worker fake). Assert `len(FakePortWorker.instances) == 1` after `start_bridge` and that some emitted message `text` contains `the stream` and not `both streams`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_hub.HubTest.test_update_slots_can_drop_to_one_target_in_crt tests.test_hub.HubTest.test_update_slots_can_add_second_target_in_crt tests.test_hub.HubTest.test_update_slots_keeps_remaining_target_log_when_removing_other tests.test_hub.HubTest.test_update_slots_rejects_count_change_in_bridge_mode`

Expected: FAIL — `_apply_slot_updates` `IndexError` on add, or drop leaves `rtos` in `ports`; `add_defaults` missing.

- [ ] **Step 3: Write minimal implementation**

Replace `_apply_slot_updates` body:

```python
    def _apply_slot_updates(self, slots: list[dict[str, str | int]]) -> None:
        new_ports: dict[str, dict[str, Any]] = {}
        for index, slot in enumerate(slots):
            new_name = str(slot["name"])
            old_name = (
                str(self.config.slots[index]["name"])
                if index < len(self.config.slots)
                else None
            )
            if new_name in self.ports:
                entry = dict(self.ports[new_name])
            elif old_name is not None and old_name in self.ports and old_name == new_name:
                entry = dict(self.ports[old_name])
            else:
                entry = {"log": None}
            entry.update(
                {
                    "name": new_name,
                    "title": str(slot["title"]),
                    "com": str(slot["com"]),
                    "baud": int(slot["baud"]),
                }
            )
            new_ports[new_name] = entry
        self.ports = new_ports
        self.config.slots = slots
        self.config.warning = None
```

In `status()`, after building the payload, if `len(self.config.slots) < MAX_SLOT_COUNT:` set `payload["add_defaults"] = unused_default_slot(self.config.slots)`.

In `mode_transition.py` system text:

```python
                    streams = (
                        "both streams"
                        if len(self._hub.ports) > 1
                        else "the stream"
                    )
                    "text": (
                        "Entered Bridge Mode: "
                        f"Agent and Operator share {streams} below"
                    ),
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest tests.test_hub -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add serial_bridge/hub/core.py serial_bridge/hub/mode_transition.py tests/test_hub.py
git commit -m "feat: Hub add/remove Target Slots in CRT and expose add_defaults"
```

---

### Task 5: Bindings HTTP accepts one or two Slots

**Files:**
- Modify: `serial_bridge/operator.py` (`BindingsBody.slots` `Field(min_length=1, max_length=2)`)
- Test: `tests/test_app.py`

**Interfaces:**
- Consumes: Task 4 `Hub.update_slots`.
- `POST /api/bindings` body `slots` length 1 or 2. Length 0 or 3 remains HTTP 422 (Pydantic).
- Existing loopback persist-and-restart test stays two-slot.
- Replace `test_binding_update_requires_both_slots` (currently expects 422 for one slot).

- [ ] **Step 1: Write the failing tests**

Rename/replace `test_binding_update_requires_both_slots` with:

```python
    def test_binding_update_rejects_zero_or_three_slots(self):
        client = TestClient(app_module.app, client=("127.0.0.1", 50000))

        empty = client.post("/api/bindings", json={"slots": []})
        three = client.post(
            "/api/bindings",
            json={
                "slots": [
                    {"name": "linux", "title": "Linux", "com": "COM8", "baud": 57600},
                    {"name": "rtos", "title": "RTOS", "com": "COM9", "baud": 115200},
                    {"name": "extra", "title": "Extra", "com": "COM7", "baud": 9600},
                ]
            },
        )

        self.assertEqual(422, empty.status_code)
        self.assertEqual(422, three.status_code)

    def test_loopback_binding_update_persists_one_slot(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "serial_bridge.json"
            current = Config(
                slots=[
                    {"name": "linux", "title": "Linux", "com": "COM3", "baud": 115200},
                    {"name": "rtos", "title": "RTOS", "com": "COM6", "baud": 115200},
                ],
                path=config_path,
            )
            client = TestClient(app_module.app, client=("127.0.0.1", 50000))
            with patch.object(app_module, "hub", Hub(current)):
                response = client.post(
                    "/api/bindings",
                    json={
                        "slots": [
                            {
                                "name": "linux",
                                "title": "Linux",
                                "com": "COM8",
                                "baud": 57600,
                            }
                        ]
                    },
                )

            restarted = Hub(load_config(environ={}, config_path=config_path))
            saved = json.loads(config_path.read_text(encoding="utf-8"))

        self.assertEqual(200, response.status_code)
        self.assertTrue(response.json()["ok"])
        self.assertEqual(["linux"], list(response.json()["ports"]))
        self.assertNotIn("rtos", restarted.status()["ports"])
        self.assertEqual(1, len(saved["slots"]))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_app.AppHttpAuthorizationTest.test_binding_update_rejects_zero_or_three_slots tests.test_app.AppHttpAuthorizationTest.test_loopback_binding_update_persists_one_slot`

Expected: FAIL — one-slot POST is 422; three-slot may already be 422 (characterization).

- [ ] **Step 3: Write minimal implementation**

In `serial_bridge/operator.py`:

```python
class BindingsBody(BaseModel):
    slots: list[SlotBindingBody] = Field(min_length=1, max_length=2)
    live_dir: str | None = Field(default=None, min_length=1)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest tests.test_app -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add serial_bridge/operator.py tests/test_app.py
git commit -m "feat: accept one or two Slots on POST /api/bindings"
```

---

### Task 6: Operator UI shows one pane when one Target exists

**Files:**
- Modify: `static/index.html` — add `id="tube-slot0"`, `id="tube-slot1"`, `id="binding-row-slot0"`, `id="binding-row-slot1"`, `id="binding-strip-seg-slot0"`, `id="binding-strip-seg-slot1"` on the existing tube / binding-slot / binding-segment elements.
- Modify: `static/app.js` — `applyStatus` hides unused chrome; Save / notes use only active Slots.
- Modify: `static/style.css` — optional: when only one tube is visible, it still fills the console area (no empty second column). If `.main` / tube grid assumes two children, hide must collapse the gap (e.g. `#tube-slot1[hidden] { display: none; }` and the remaining tube grows).
- Test: `tests/test_ground_station_exec_ui.py`

**Interfaces:**
- Consumes: `status.ports` insertion order (same as `config.slots`). `SLOT_KEYS[index]` maps the nth Target.
- Produces: `function activeSlotKeys()` → `SLOT_KEYS.slice(0, portEntries(lastPorts).length || slotTargets.length)` using the last `applyStatus` ports. If no status yet, both keys (boot default is two).
- `applyStatus`: for `index >= entries.length`, set `hidden = true` on `tube-slot{N}`, `binding-row-slot{N}`, `binding-strip-seg-slot{N}`. For present indices, `hidden = false`.
- Header `bindingsSummary`: one Target → `{title} ({name}) @ {baud}`; two Targets keep today’s two-slot string.
- `refreshBindingNotes` and the Save `slots:` array iterate `activeSlotKeys()` only, not all `SLOT_KEYS`.
- Agent Trace is not hidden.
- Do not add Add/Remove controls in this task.

- [ ] **Step 1: Write the failing test**

Add to `GroundStationExecUiTest` (same `run_ui_scenario` harness; `getElementById` creates missing ids):

```python
    def test_one_target_status_hides_second_pane_and_binding_row(self):
        result = run_ui_scenario(
            """
  send({
    type: "status",
    mode: "crt",
    ports: {
      linux: { name: "linux", title: "Linux", com: "COM3", baud: 115200, open: false },
    },
  });
  return {
    tube1Hidden: document.getElementById("tube-slot1").hidden,
    row1Hidden: document.getElementById("binding-row-slot1").hidden,
    strip1Hidden: document.getElementById("binding-strip-seg-slot1").hidden,
    tube0Hidden: document.getElementById("tube-slot0").hidden,
    summary: document.getElementById("bindings-summary").textContent,
    spinePresent: Boolean(document.getElementById("spine-body")),
  };
"""
        )
        self.assertTrue(result["tube1Hidden"])
        self.assertTrue(result["row1Hidden"])
        self.assertTrue(result["strip1Hidden"])
        self.assertFalse(result["tube0Hidden"])
        self.assertIn("Linux", result["summary"])
        self.assertNotIn("RTOS", result["summary"])
        self.assertTrue(result["spinePresent"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_ground_station_exec_ui.GroundStationExecUiTest.test_one_target_status_hides_second_pane_and_binding_row`

Expected: FAIL — `tube1Hidden` is false; summary still requires `entries.length >= 2` and stays at `reading bindings…` or the two-slot sentence.

- [ ] **Step 3: Write minimal implementation**

HTML: add the six ids listed above (do not remove existing classes).

JS: store `let lastPortCount = 2`. In `applyStatus` when `s.ports` is present:

```javascript
      const entries = portEntries(s.ports);
      lastPortCount = entries.length;
      SLOT_KEYS.forEach((slot, index) => {
        const hidden = index >= entries.length;
        const tube = document.getElementById(`tube-${slot}`);
        const row = document.getElementById(`binding-row-${slot}`);
        const strip = document.getElementById(`binding-strip-seg-${slot}`);
        if (tube) tube.hidden = hidden;
        if (row) row.hidden = hidden;
        if (strip) strip.hidden = hidden;
      });
```

Summary:

```javascript
      if (entries.length === 1) {
        const only = entries[0][1];
        bindingsSummary.textContent =
          `${only.title} (${only.name}) @ ${only.baud}`;
      } else if (entries.length >= 2) {
        // existing two-slot string
      }
```

`activeSlotKeys()` returns `SLOT_KEYS.slice(0, lastPortCount)`. Use it in `refreshBindingNotes` and the Save body.

CSS: `#tube-slot1[hidden], #binding-row-slot1[hidden], #binding-strip-seg-slot1[hidden] { display: none; }` if `[hidden]` is overridden by the tube grid.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest tests.test_ground_station_exec_ui.GroundStationExecUiTest.test_one_target_status_hides_second_pane_and_binding_row tests.test_ground_station_exec_ui -q`

Expected: PASS (new test + existing UI suite).

- [ ] **Step 5: Commit**

```bash
git add static/index.html static/app.js static/style.css tests/test_ground_station_exec_ui.py
git commit -m "feat: hide the second Operator pane when only one Target exists"
```

---

### Task 7: Add Target dialog and Remove confirm

**Files:**
- Modify: `static/index.html` — CRT Bindings actions: `button#btn-add-target` (visible when one Target), `button#btn-remove-slot0` / `button#btn-remove-slot1` on each binding row (visible when two Targets). Add panel `#add-target-dialog` (hidden by default) with `#add-target-title`, `#add-target-com`, `#add-target-baud`, `#btn-add-target-confirm`, `#btn-add-target-cancel`.
- Modify: `static/app.js`
- Test: `tests/test_ground_station_exec_ui.py`

**Interfaces:**
- Consumes: Task 5 `POST /api/bindings` 1–2 slots; Task 4 `add_defaults`; Task 6 `activeSlotKeys` / hide chrome; existing `deriveTargetName`, `fillPortOptions`, `refreshBindingNotes`.
- Add opens the panel only in CRT. Fields prefilled from last status `add_defaults` (fallback: if remaining Target Name is `linux`, use `DEFAULT` twin `rtos`/COM6/115200, else `linux`/COM3/115200). Confirm POSTs `[...currentActiveFormSlots(), newSlot]`. Cancel hides the panel and POSTs nothing. Derived name clash or invalid title: do not POST; show the same note language as Bindings.
- Remove on a row: `globalThis.confirm("Remove this Target? Agents will no longer be able to address it.")`. If false, no POST. If true, POST the other Slot’s current form values only.
- Both POSTs include `live_dir: bindingLiveDir.value.trim()` and current form values (dirty Slot 0 COM must be in the body).
- On success, `bindingsDirty = false` and `applyStatus(data)` as Save does. Fake harness fetch returns `{ok: true}` only — tests assert `fetchRequests`, then may `send` a follow-up status if they need chrome updates.
- Hide `#btn-add-target` when two Targets or mode is Bridge. Hide Remove buttons when one Target or Bridge.

- [ ] **Step 1: Write the failing tests**

```python
    def test_add_target_confirm_posts_defaults_and_dirty_existing_slot(self):
        result = run_ui_scenario(
            """
  send({
    type: "status",
    mode: "crt",
    add_defaults: { name: "rtos", title: "RTOS", com: "COM6", baud: 115200 },
    ports: {
      linux: { name: "linux", title: "Linux", com: "COM3", baud: 115200, open: false },
    },
    live_dir: "D:/live",
  });
  document.getElementById("binding-slot0-com").value = "COM19";
  document.getElementById("btn-add-target").dispatch("click");
  const title = document.getElementById("add-target-title").value;
  const com = document.getElementById("add-target-com").value;
  const baud = document.getElementById("add-target-baud").value;
  document.getElementById("btn-add-target-confirm").dispatch("click");
  await nextTurn();
  const posted = fetchRequests.filter((item) => item.url === "/api/bindings").pop();
  return {
    title, com, baud: Number(baud),
    dialogHiddenAfterOpen: document.getElementById("add-target-dialog").hidden === false,
    body: JSON.parse(posted.options.body),
  };
"""
        )
        self.assertEqual("RTOS", result["title"])
        self.assertEqual("COM6", result["com"])
        self.assertEqual(115200, result["baud"])
        self.assertEqual("COM19", result["body"]["slots"][0]["com"])
        self.assertEqual("rtos", result["body"]["slots"][1]["name"])
        self.assertEqual("RTOS", result["body"]["slots"][1]["title"])
        self.assertEqual(2, len(result["body"]["slots"]))

    def test_add_target_cancel_does_not_post(self):
        result = run_ui_scenario(
            """
  send({
    type: "status",
    mode: "crt",
    add_defaults: { name: "rtos", title: "RTOS", com: "COM6", baud: 115200 },
    ports: {
      linux: { name: "linux", title: "Linux", com: "COM3", baud: 115200, open: false },
    },
  });
  const before = fetchRequests.length;
  document.getElementById("btn-add-target").dispatch("click");
  document.getElementById("btn-add-target-cancel").dispatch("click");
  await nextTurn();
  return {
    hidden: document.getElementById("add-target-dialog").hidden,
    extraPosts: fetchRequests.length - before,
  };
"""
        )
        self.assertTrue(result["hidden"])
        self.assertEqual(0, result["extraPosts"])

    def test_remove_target_posts_other_slot_only_after_confirm(self):
        result = run_ui_scenario(
            """
  globalThis.confirm = () => true;
  send({
    type: "status",
    mode: "crt",
    ports: {
      linux: { name: "linux", title: "Linux", com: "COM3", baud: 115200, open: false },
      rtos: { name: "rtos", title: "RTOS", com: "COM6", baud: 115200, open: false },
    },
    live_dir: "D:/live",
  });
  document.getElementById("binding-slot0-com").value = "COM19";
  document.getElementById("btn-remove-slot1").dispatch("click");
  await nextTurn();
  const posted = fetchRequests.filter((item) => item.url === "/api/bindings").pop();
  return { body: JSON.parse(posted.options.body) };
"""
        )
        self.assertEqual(1, len(result["body"]["slots"]))
        self.assertEqual("linux", result["body"]["slots"][0]["name"])
        self.assertEqual("COM19", result["body"]["slots"][0]["com"])

    def test_remove_target_cancel_confirm_does_not_post(self):
        result = run_ui_scenario(
            """
  globalThis.confirm = () => false;
  send({
    type: "status",
    mode: "crt",
    ports: {
      linux: { name: "linux", title: "Linux", com: "COM3", baud: 115200, open: false },
      rtos: { name: "rtos", title: "RTOS", com: "COM6", baud: 115200, open: false },
    },
  });
  const before = fetchRequests.length;
  document.getElementById("btn-remove-slot1").dispatch("click");
  await nextTurn();
  return { extraPosts: fetchRequests.length - before };
"""
        )
        self.assertEqual(0, result["extraPosts"])
```

If a scenario is not `async`, wrap it so `await nextTurn()` works (other tests in this file already use `await nextTurn()` inside the async IIFE).

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_ground_station_exec_ui.GroundStationExecUiTest.test_add_target_confirm_posts_defaults_and_dirty_existing_slot tests.test_ground_station_exec_ui.GroundStationExecUiTest.test_add_target_cancel_does_not_post tests.test_ground_station_exec_ui.GroundStationExecUiTest.test_remove_target_posts_other_slot_only_after_confirm tests.test_ground_station_exec_ui.GroundStationExecUiTest.test_remove_target_cancel_confirm_does_not_post`

Expected: FAIL — buttons missing or no POST.

- [ ] **Step 3: Write minimal implementation**

HTML: Add / Remove buttons and `#add-target-dialog` panel as specified. Reuse Binding field markup (title input, COM select, baud input). Dialog starts `hidden`.

JS sketch (keep helpers next to the Save handler):

```javascript
  function currentActiveFormSlots() {
    const { names, valid } = refreshBindingNotes();
    if (!valid) return null;
    return activeSlotKeys().map((slot, index) => ({
      name: names[index],
      title: bindingInputs[slot].title.value.trim(),
      com: bindingInputs[slot].com.value,
      baud: Number(bindingInputs[slot].baud.value),
    }));
  }

  async function postSlots(slots) {
    const response = await fetch("/api/bindings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        live_dir: bindingLiveDir.value.trim(),
        slots,
      }),
    });
    const data = await response.json();
    if (!response.ok || !data.ok) {
      throw new Error(data.error || data.detail || "save failed");
    }
    bindingsDirty = false;
    applyStatus(data);
    return data;
  }
```

Prefill Add from `lastAddDefaults` stored in `applyStatus`. Confirm derives `name` with `deriveTargetName`. Cancel only sets `add-target-dialog.hidden = true`.

Remove: if `!globalThis.confirm(...)` return; else `postSlots` of the other row’s current values.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest tests.test_ground_station_exec_ui -q tests.test_app -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add static/index.html static/app.js static/style.css tests/test_ground_station_exec_ui.py
git commit -m "feat: CRT Add Target dialog and confirmed Remove"
```

---

### Task 8: README and leftover two-slot copy

**Files:**
- Modify: `README.md`
- Modify: `serial_bridge/app.py` module docstring (`Visual dual-serial console` → one or two)
- Test: `tests/test_config.py` (`test_readme_documents_live_directory` style) — add `test_readme_documents_one_or_two_slots`

**Interfaces:**
- Consumes: all prior behavior.
- README opening sentence: Hub shares one or two serial consoles.
- Port Binding section: CRT Add/Remove; one-slot `slots[]` JSON is valid; Slot 1 env/CLI with a one-slot file fails startup; Agents still pass `target` (examples may keep `linux` / `rtos`).
- Do not rewrite MCP tool contracts.

- [ ] **Step 1: Write the failing test**

```python
    def test_readme_documents_one_or_two_slots(self):
        readme = (APP_DIR / "README.md").read_text(encoding="utf-8")
        self.assertIn("one or two", readme.lower())
        self.assertIn("only one Slot", readme)
```

If you phrase the env error in README as “Slot 1 … only one Slot”, keep that exact substring. If README uses another sentence, change the assertion to a unique phrase you actually write in Step 3 — write the test to the phrase first, then the README.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_config.ConfigTest.test_readme_documents_one_or_two_slots`

Expected: FAIL — README still says “shares two serial consoles”.

- [ ] **Step 3: Write minimal implementation**

Update `README.md` lines 3–4 and the Port Binding section (after the load-order paragraph) with:

- Operator may add a second Target or remove one Target in CRT Mode.
- A persisted `slots` array of length 1 is valid and is the count.
- `SERIAL_BRIDGE_RTOS_*` / `--rtos-port` / `--rtos-baud` / `SERIAL_BRIDGE_SLOT1_*` fail startup when that file has one Slot.

`serial_bridge/app.py` first line docstring: `Visual one- or two-serial console.`

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest tests.test_config.ConfigTest.test_readme_documents_one_or_two_slots tests.test_config -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add README.md serial_bridge/app.py tests/test_config.py
git commit -m "docs: document one or two Target Slots"
```

---

## Self-review

**Spec coverage**

| Decision | Task |
|---|---|
| Count is 1 or 2; absent Target does not exist | 1, 4, 5, 6 |
| Default remains 2 | 1 (no-file path unchanged) |
| File `slots.length` is count; no pad | 1 |
| Slot 1 env/CLI + one-slot file fails startup | 2 |
| Operator add/remove only in CRT | 3, 4, 7 |
| Immediate persist including dirty form | 4, 5, 7 |
| Add dialog + unused default twin | 1 `unused_default_slot`, 4 `add_defaults`, 7 |
| Remove confirm; Operator chooses which | 7 |
| One pane; Agent Trace stays | 6 |
| MCP `target` still required | no MCP change (intentional) |
| Index aliases unchanged | 2 (Slot 0 overlays still work) |
| Legacy two-key `ports` stays two Slots | 1 (`_legacy_ports_to_slots` untouched) |
| README / ADR-0020 / ADR-0030 | ADR already written; Task 8 README |

**Placeholder scan:** no TBD/TODO/“implement later”.

**Type consistency:** `unused_default_slot` → `add_defaults` on `status()` → Add dialog; `MIN_SLOT_COUNT`/`MAX_SLOT_COUNT` used by parse, persist, SlotPolicy, BindingsBody, `add_defaults`.

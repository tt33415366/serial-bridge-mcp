(() => {
  const SLOT_KEYS = ["slot0", "slot1"];
  const statusPill = document.getElementById("status-pill");
  const modeLabel = document.getElementById("mode-label");
  const modeHint = document.getElementById("mode-hint");
  const btnBridge = document.getElementById("btn-bridge");
  const btnCrt = document.getElementById("btn-crt");
  const bindingForm = document.getElementById("binding-form");
  const bindingHint = document.getElementById("binding-hint");
  const btnSaveBindings = document.getElementById("btn-save-bindings");
  const btnScanPorts = document.getElementById("btn-scan-ports");
  const bindingsSummary = document.getElementById("bindings-summary");
  const bindingLiveDir = document.getElementById("binding-live-dir");
  const bindingLiveDirField = document.getElementById("binding-live-dir-field");
  const footLiveDir = document.getElementById("foot-live-dir");
  const footLogsLabel = document.getElementById("foot-logs-label");
  const footSessionLogs = document.getElementById("foot-session-logs");
  const bindingInputs = Object.fromEntries(
    SLOT_KEYS.map((slot) => [
      slot,
      {
        title: document.getElementById(`binding-${slot}-title`),
        com: document.getElementById(`binding-${slot}-com`),
        baud: document.getElementById(`binding-${slot}-baud`),
      },
    ])
  );
  const bindingNotes = {
    slot0: document.getElementById("note-slot0"),
    slot1: document.getElementById("note-slot1"),
  };
  const paneTitles = {
    slot0: document.getElementById("title-slot0"),
    slot1: document.getElementById("title-slot1"),
  };
  const portLabels = {
    slot0: document.getElementById("port-slot0"),
    slot1: document.getElementById("port-slot1"),
  };
  const terms = {
    slot0: document.getElementById("term-slot0"),
    slot1: document.getElementById("term-slot1"),
  };
  const dots = {
    slot0: document.getElementById("dot-slot0"),
    slot1: document.getElementById("dot-slot1"),
  };

  let ws;
  let mode = "crt";
  let bindingsDirty = false;
  let knownPorts = [];
  let slotTargets = ["linux", "rtos"];
  let targetToSlot = { linux: "slot0", rtos: "slot1" };
  const savedSlots = {};

  function portEntries(ports) {
    if (!ports) return [];
    return Object.entries(ports);
  }

  function syncTargetMaps(ports) {
    const entries = portEntries(ports);
    slotTargets = entries.map(([name]) => name);
    targetToSlot = {};
    entries.forEach(([name], index) => {
      targetToSlot[name] = SLOT_KEYS[index] || name;
    });
  }

  function fillPortOptions(select, current) {
    const options = knownPorts.slice();
    if (current && !options.some((port) => port.com === current)) {
      options.unshift({ com: current, label: "not detected" });
    }
    const signature = options.map((p) => `${p.com}|${p.label}`).join("\n") + `\n=${current}`;
    if (select.dataset.signature === signature) return;
    select.textContent = "";
    for (const port of options) {
      const option = document.createElement("option");
      option.value = port.com;
      option.textContent = port.label ? `${port.com} — ${port.label}` : port.com;
      select.appendChild(option);
    }
    if (current) select.value = current;
    select.dataset.signature = signature;
  }

  async function refreshPorts() {
    try {
      const response = await fetch("/api/ports");
      const data = await response.json();
      if (!response.ok || !data.ok) throw new Error(data.detail || "scan failed");
      knownPorts = data.ports || [];
    } catch {
      knownPorts = [];
    }
    for (const slot of SLOT_KEYS) {
      fillPortOptions(bindingInputs[slot].com, bindingInputs[slot].com.value);
    }
  }

  function setPill(text, cls) {
    statusPill.textContent = text;
    statusPill.className = "status-pill " + (cls || "");
  }

  function setBindingEditability() {
    const crtEditable = mode === "crt";
    btnSaveBindings.disabled = !crtEditable;
    btnScanPorts.disabled = !crtEditable;
    for (const slot of SLOT_KEYS) {
      bindingInputs[slot].title.disabled = !crtEditable;
      bindingInputs[slot].com.disabled = !crtEditable;
      bindingInputs[slot].baud.disabled = !crtEditable;
    }
    bindingLiveDir.disabled = !crtEditable;
    bindingLiveDirField.hidden = !crtEditable;
    bindingHint.textContent = crtEditable
      ? "Target name follows the title, lowercased."
      : "Switch to CRT to edit bindings.";
  }

  const TARGET_NAME_RE = /^[a-z][a-z0-9_]{0,31}$/;

  function deriveTargetName(title) {
    return title
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9_]+/g, "_")
      .slice(0, 32)
      .replace(/^_+|_+$/g, "");
  }

  /** Keep the stored name while the title is untouched; a saved config may predate this rule. */
  function resolveTargetName(slot) {
    const title = bindingInputs[slot].title.value;
    const saved = savedSlots[slot];
    if (saved && title === saved.title) return { name: saved.name, ok: true };
    const name = deriveTargetName(title);
    return { name, ok: TARGET_NAME_RE.test(name) };
  }

  function refreshBindingNotes() {
    const resolved = SLOT_KEYS.map(resolveTargetName);
    let valid = true;
    resolved.forEach((entry, index) => {
      const note = bindingNotes[SLOT_KEYS[index]];
      const clash =
        entry.ok && resolved.some((other, i) => i !== index && other.ok && other.name === entry.name);
      if (!entry.ok) note.textContent = "title needs a letter a–z to name the target";
      else if (clash) note.textContent = `target ${entry.name} · already used by the other slot`;
      else note.textContent = `target ${entry.name}`;
      note.classList.toggle("err", !entry.ok || clash);
      if (!entry.ok || clash) valid = false;
    });
    return { names: resolved.map((entry) => entry.name), valid };
  }

  function basename(path) {
    if (!path) return "";
    const parts = path.split(/[/\\]/);
    return parts[parts.length - 1] || path;
  }

  function updateFooterLogs(s) {
    if (s.live_dir) footLiveDir.textContent = s.live_dir;
    const logs = Object.values(s.ports || {})
      .map((binding) => binding.log)
      .filter(Boolean);
    if (logs.length) {
      footLogsLabel.hidden = false;
      footSessionLogs.textContent = logs.map(basename).join(" · ");
    } else {
      footLogsLabel.hidden = true;
      footSessionLogs.textContent = "";
    }
  }

  function applyStatus(s) {
    mode = s.mode || "crt";
    btnBridge.classList.toggle("active-bridge", mode === "bridge");
    btnCrt.classList.toggle("active-crt", mode === "crt");
    setBindingEditability();
    if (mode === "bridge") {
      modeLabel.textContent = "Bridge";
      modeHint.textContent = "Hub owns ports. You and Agent share the streams (colors differ).";
      setPill("Bridge · ports held", "ok");
    } else {
      modeLabel.textContent = "CRT";
      modeHint.textContent = "Ports released for SecureCRT. Disconnect CRT before Bridge.";
      setPill("CRT · ports free", "warn");
    }
    if (s.ports) {
      syncTargetMaps(s.ports);
      const entries = portEntries(s.ports);
      entries.forEach(([name, binding], index) => {
        const slot = SLOT_KEYS[index];
        if (!slot || !binding) return;
        dots[slot].classList.toggle("on", !!binding.open);
        paneTitles[slot].textContent = binding.title || name;
        portLabels[slot].textContent = `${name} · ${binding.com} @ ${binding.baud}`;
        savedSlots[slot] = { name: binding.name || name, title: binding.title || name };
        if (!bindingsDirty) {
          bindingInputs[slot].title.value = binding.title || name;
          fillPortOptions(bindingInputs[slot].com, binding.com);
          bindingInputs[slot].baud.value = binding.baud;
        }
      });
      refreshBindingNotes();
      if (entries.length >= 2) {
        const first = entries[0][1];
        const second = entries[1][1];
        bindingsSummary.textContent =
          `${first.title} (${first.name}) · ${second.title} (${second.name}) @ ${first.baud}/${second.baud}`;
      }
    }
    if (s.live_dir) {
      if (!bindingsDirty) bindingLiveDir.value = s.live_dir;
    }
    updateFooterLogs(s);
    if (s.error) setPill(s.error, "err");
    if (s.config_warning) setPill(s.config_warning, "err");
  }

  const MAX_TERM_LINES = 75000;

  function trimTerm(el) {
    while (el.childElementCount > MAX_TERM_LINES) {
      el.removeChild(el.firstElementChild);
    }
  }

  function appendLine(target, direction, text, who, tstamp) {
    const slot = targetToSlot[target] || SLOT_KEYS[0];
    const el = terms[slot];
    if (!el) return;
    const row = document.createElement("div");
    let cls = "line out";
    let tag = "DEV";
    if (direction === ">>>") {
      cls = who === "agent" ? "line in-agent" : "line in-user";
      tag = who === "agent" ? "AGENT" : "YOU";
    } else if (direction === "---") {
      cls = "line sys";
      tag = "SYS";
    }
    row.className = cls;
    const meta = document.createElement("span");
    meta.className = "meta";
    meta.textContent = `${tstamp || ""} ${tag}`;
    const body = document.createElement("span");
    body.className = "body";
    AnsiRender.renderAnsi(body, text);
    row.append(meta, document.createTextNode(" "), body);
    el.appendChild(row);
    trimTerm(el);
    el.scrollTop = el.scrollHeight;
  }

  function connect() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    ws = new WebSocket(`${proto}://${location.host}/ws`);
    ws.onopen = () => setPill("WS linked", "ok");
    ws.onclose = () => {
      setPill("WS dropped · retry", "warn");
      setTimeout(connect, 1200);
    };
    ws.onerror = () => setPill("WS error", "err");
    ws.onmessage = (ev) => {
      let msg;
      try { msg = JSON.parse(ev.data); } catch { return; }
      if (msg.type === "status" || (msg.mode && msg.ports)) applyStatus(msg);
      if (msg.type === "line") appendLine(msg.target, msg.direction, msg.text, msg.who, msg.ts);
      if (msg.type === "system") {
        for (const target of slotTargets) {
          appendLine(target, "---", msg.text, "system", "");
        }
      }
      if (msg.type === "ack" && msg.error) {
        setPill(msg.error, "err");
        appendLine(slotTargets[0], "---", msg.error, "system", "");
      }
    };
  }

  async function setMode(modeName) {
    setPill("switching…", "warn");
    const res = await fetch("/api/mode", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode: modeName }),
    });
    const data = await res.json();
    if (!data.ok) {
      setPill(data.error || "mode failed", "err");
      appendLine(slotTargets[0], "---", data.error || "mode failed", "system", "");
    }
    applyStatus(await (await fetch("/api/status")).json());
    await refreshPorts();
  }

  btnBridge.addEventListener("click", () => setMode("bridge"));
  btnCrt.addEventListener("click", () => setMode("crt"));

  bindingLiveDir.addEventListener("input", () => {
    bindingsDirty = true;
  });
  bindingLiveDir.addEventListener("change", () => {
    bindingsDirty = true;
  });

  for (const slot of SLOT_KEYS) {
    for (const field of ["title", "com", "baud"]) {
      const markDirty = () => {
        bindingsDirty = true;
        refreshBindingNotes();
      };
      bindingInputs[slot][field].addEventListener("input", markDirty);
      bindingInputs[slot][field].addEventListener("change", markDirty);
    }
  }

  btnScanPorts.addEventListener("click", async () => {
    btnScanPorts.disabled = true;
    bindingHint.textContent = "scanning…";
    await refreshPorts();
    bindingHint.textContent = knownPorts.length
      ? `${knownPorts.length} port(s) detected.`
      : "No ports detected.";
    setBindingEditability();
  });

  bindingForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const { names, valid } = refreshBindingNotes();
    if (!valid) {
      bindingHint.textContent = "Fix the flagged title before saving.";
      setPill("bindings not saved", "err");
      return;
    }
    btnSaveBindings.disabled = true;
    bindingHint.textContent = "saving…";
    try {
      const response = await fetch("/api/bindings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          live_dir: bindingLiveDir.value.trim(),
          slots: SLOT_KEYS.map((slot, index) => ({
            name: names[index],
            title: bindingInputs[slot].title.value.trim(),
            com: bindingInputs[slot].com.value,
            baud: Number(bindingInputs[slot].baud.value),
          })),
        }),
      });
      const data = await response.json();
      if (!response.ok || !data.ok) {
        throw new Error(data.error || data.detail || "save failed");
      }
      bindingsDirty = false;
      applyStatus(data);
      bindingHint.textContent = "Saved — survives restart.";
      setPill("bindings saved", "ok");
    } catch (error) {
      bindingHint.textContent = error.message || "save failed";
      setPill(error.message || "save failed", "err");
    } finally {
      setBindingEditability();
    }
  });

  document.querySelectorAll(".composer").forEach((form) => {
    const index = Number.parseInt(form.getAttribute("data-slot"), 10);
    const slot = SLOT_KEYS[index];
    const input = form.querySelector("input");
    const historyState = {
      history: CommandHistory.loadHistory(localStorage, slot),
      browser: null,
    };
    historyState.browser = CommandHistory.createBrowser(historyState.history);
    let programmaticInput = false;

    function setInputValue(value) {
      input.value = value;
      const end = value.length;
      input.setSelectionRange(end, end);
    }

    input.addEventListener("input", () => {
      if (!programmaticInput) {
        historyState.browser.reset();
      }
    });

    input.addEventListener("keydown", (e) => {
      if (e.key !== "ArrowUp" && e.key !== "ArrowDown") return;
      e.preventDefault();
      const result =
        e.key === "ArrowUp"
          ? historyState.browser.arrowUp(input.value)
          : historyState.browser.arrowDown(input.value);
      if (!result.changed) return;
      programmaticInput = true;
      setInputValue(result.value);
      programmaticInput = false;
    });

    form.addEventListener("submit", (e) => {
      e.preventDefault();
      const target = slotTargets[index];
      const cmd = input.value;
      const trimmed = cmd.trim();
      if (!trimmed || !target) return;
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "send", target, cmd }));
      } else {
        fetch("/api/send", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ target, cmd }),
        });
      }
      historyState.history = CommandHistory.recordCommand(historyState.history, trimmed);
      CommandHistory.saveHistory(localStorage, slot, historyState.history);
      historyState.browser = CommandHistory.createBrowser(historyState.history);
      input.value = "";
      input.focus();
    });
  });

  document.getElementById("btn-clear").addEventListener("click", () => {
    terms.slot0.innerHTML = "";
    terms.slot1.innerHTML = "";
  });

  connect();
  fetch("/api/status")
    .then((r) => r.json())
    .then(applyStatus)
    .then(refreshPorts);
})();

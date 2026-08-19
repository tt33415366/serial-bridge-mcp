(() => {
  const SLOT_KEYS = ["slot0", "slot1"];
  const statusPill = document.getElementById("status-pill");
  const modeLabel = document.getElementById("mode-label");
  const modeHint = document.getElementById("mode-hint");
  const btnBridge = document.getElementById("btn-bridge");
  const btnCrt = document.getElementById("btn-crt");
  const bindingStrip = document.getElementById("binding-strip");
  const bindingForm = document.getElementById("binding-form");
  const bindingHint = document.getElementById("binding-hint");
  const btnSaveBindings = document.getElementById("btn-save-bindings");
  const btnScanPorts = document.getElementById("btn-scan-ports");
  const bindingsSummary = document.getElementById("bindings-summary");
  const bindingStripSlots = {
    slot0: document.getElementById("binding-strip-slot0"),
    slot1: document.getElementById("binding-strip-slot1"),
  };
  const wsLamp = document.getElementById("ws-lamp");
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
  const holders = {
    slot0: document.getElementById("holder-slot0"),
    slot1: document.getElementById("holder-slot1"),
  };
  const spineBody = document.getElementById("spine-body");
  const spineTally = document.getElementById("spine-tally");
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
  const openCaptures = {};
  const captureIndex = new Map();
  let spineEntries = [];
  let hydrateVersion = 0;
  const termLineCounts = new WeakMap();
  let jumpFlashTimer = null;

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
    restoreHydratedHolders();
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

  function setWsLamp(cls) {
    wsLamp.className = "lamp " + (cls || "");
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
    bindingStrip.hidden = mode !== "bridge";
    bindingForm.hidden = mode !== "crt";
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
        bindingStripSlots[slot].textContent =
          `${binding.title || name} · ${name} · ${binding.com} · ${binding.baud}`;
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

  function hasClass(el, name) {
    return el.className.split(" ").includes(name);
  }

  function oldestTermLine(el) {
    for (const child of Array.from(el.children)) {
      if (hasClass(child, "ln")) return { parent: el, row: child };
      for (const nested of Array.from(child.children || [])) {
        if (hasClass(nested, "ln")) return { parent: child, row: nested };
      }
    }
    return null;
  }

  function trimTerm(el) {
    let lineCount = termLineCounts.get(el) || 0;
    while (lineCount > MAX_TERM_LINES) {
      const oldest = oldestTermLine(el);
      if (!oldest) break;
      oldest.parent.removeChild(oldest.row);
      if (
        oldest.parent !== el &&
        hasClass(oldest.parent, "sealed") &&
        !Array.from(oldest.parent.children).some((child) => hasClass(child, "ln"))
      ) {
        el.removeChild(oldest.parent);
      }
      lineCount -= 1;
    }
    termLineCounts.set(el, lineCount);
  }

  function setHolder(slot, active) {
    const holder = holders[slot];
    if (!holder) return;
    holder.className = active ? "holder agent" : "holder idle";
    holder.textContent = "";
    const pip = document.createElement("span");
    pip.className = "pip";
    holder.append(pip, document.createTextNode(active ? "AGENT EXEC" : "IDLE"));
  }

  function formatDuration(ms) {
    return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(2)} s`;
  }

  function formatBytes(bytes) {
    return bytes < 1024 ? `${bytes} B` : `${(bytes / 1024).toFixed(1)} KiB`;
  }

  function normalizedEndReason(endedBy) {
    const reasons = new Set(["idle", "prompt", "timeout", "abort", "error"]);
    return reasons.has(endedBy) ? endedBy : "error";
  }

  function sealCopy(msg) {
    const reason = normalizedEndReason(msg.ended_by);
    const ending = reason === "abort" ? "aborted" : `closed on ${reason}`;
    const capped = msg.truncated ? " · capped" : "";
    return `captured ${formatDuration(msg.ms)} · ${formatBytes(msg.bytes)} · ${ending}${capped}`;
  }

  function median(values) {
    if (!values.length) return null;
    const ordered = values.slice().sort((a, b) => a - b);
    const middle = Math.floor(ordered.length / 2);
    if (ordered.length % 2) return ordered[middle];
    return Math.round((ordered[middle - 1] + ordered[middle]) / 2);
  }

  function appendSpineText(parent, className, text) {
    const child = document.createElement("div");
    child.className = className;
    child.textContent = text;
    parent.appendChild(child);
  }

  function captureStillInTerm(el) {
    let node = el;
    while (node) {
      if (node === terms.slot0 || node === terms.slot1) return true;
      node = node.parentNode;
    }
    return false;
  }

  function registerCapture(id, el) {
    captureIndex.set(Number(id), el);
  }

  function clearCaptureIndex() {
    captureIndex.clear();
  }

  function traceJump(execId) {
    const el = captureIndex.get(Number(execId));
    if (!el || !captureStillInTerm(el)) {
      setPill("not in view", "warn");
      return;
    }
    if (typeof el.scrollIntoView === "function") {
      el.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
    el.classList.add("jump-flash");
    if (jumpFlashTimer) clearTimeout(jumpFlashTimer);
    jumpFlashTimer = setTimeout(() => {
      el.classList.remove("jump-flash");
      jumpFlashTimer = null;
    }, 1200);
  }

  function renderSpine() {
    spineBody.textContent = "";
    for (const entry of spineEntries) {
      const node = document.createElement("article");
      if (entry.kind === "send") {
        node.className = "spine-node send";
        appendSpineText(node, "spine-kicker", `SEND · ${entry.target} · ${entry.ts || "now"}`);
        appendSpineText(node, "spine-command", entry.cmd);
        appendSpineText(node, "spine-meta", "fire-and-forget");
      } else {
        const running = entry.phase === "start";
        const endedBy = normalizedEndReason(entry.ended_by);
        const flags = [
          "spine-node",
          "exec",
          running ? "running" : "sealed",
          endedBy === "abort" ? "aborted" : "",
          entry.truncated ? "capped" : "",
        ].filter(Boolean);
        node.className = flags.join(" ");
        node.dataset.execId = String(entry.id);
        node.title = "Jump to capture";
        node.addEventListener("click", () => traceJump(entry.id));
        appendSpineText(node, "spine-kicker", `EXEC · ${entry.target} · #${entry.id}`);
        appendSpineText(node, "spine-command", entry.cmd || "—");
        appendSpineText(
          node,
          "spine-meta",
          running
            ? "running"
            : `${endedBy === "abort" ? "aborted" : endedBy} · ` +
              `${formatDuration(entry.ms || 0)} · ${formatBytes(entry.bytes || 0)}` +
              (entry.truncated ? " · capped" : "")
        );
      }
      spineBody.appendChild(node);
    }

    const execs = spineEntries.filter((entry) => entry.kind === "exec");
    const sends = spineEntries.filter((entry) => entry.kind === "send");
    const sealed = execs.filter((entry) => entry.phase === "end");
    const aborted = sealed.filter((entry) => entry.ended_by === "abort").length;
    const capped = sealed.filter((entry) => entry.truncated).length;
    const medianMs = median(sealed.map((entry) => Number(entry.ms) || 0));
    spineTally.textContent =
      `exec ${execs.length} · send ${sends.length} · aborted ${aborted} · capped ${capped}` +
      ` · median ${medianMs === null ? "—" : formatDuration(medianMs)}`;
  }

  const MAX_SPINE_ENTRIES = 50;

  function capSpineEntries() {
    spineEntries = spineEntries.slice(0, MAX_SPINE_ENTRIES);
  }

  function recordExecStart(msg) {
    spineEntries = [
      { kind: "exec", ...msg },
      ...spineEntries.filter((entry) => entry.kind !== "exec" || entry.id !== msg.id),
    ];
    capSpineEntries();
    renderSpine();
  }

  function recordExecEnd(msg) {
    const index = spineEntries.findIndex(
      (entry) => entry.kind === "exec" && entry.id === msg.id
    );
    if (index < 0) return false;
    spineEntries[index] = { ...spineEntries[index], ...msg, phase: "end" };
    capSpineEntries();
    renderSpine();
    return true;
  }

  function recordAgentSend(target, cmd, ts) {
    spineEntries.unshift({ kind: "send", target, cmd, ts });
    capSpineEntries();
    renderSpine();
  }

  function entriesFromAgentLog(entries) {
    return (entries || [])
      .map((entry) => ({ kind: "exec", ...entry }))
      .slice(0, MAX_SPINE_ENTRIES);
  }

  function restoreHydratedHolders() {
    for (const slot of SLOT_KEYS) setHolder(slot, false);
    for (const entry of spineEntries) {
      if (entry.kind !== "exec" || entry.phase !== "start") continue;
      const slot = targetToSlot[entry.target];
      if (slot) setHolder(slot, true);
    }
  }

  async function hydrateAgentLog() {
    const version = ++hydrateVersion;
    try {
      const response = await fetch("/api/agent_log");
      const data = await response.json();
      if (version !== hydrateVersion || !response.ok || !data.ok) return;
      spineEntries = entriesFromAgentLog(data.entries);
      restoreHydratedHolders();
      renderSpine();
    } catch {
      // Keep the current client buffer when hydration is unavailable.
    }
  }

  function onExecStart(msg) {
    recordExecStart(msg);
    const slot = targetToSlot[msg.target];
    const term = terms[slot];
    if (!term) return;
    const capture = document.createElement("div");
    capture.className = "capture running";
    capture.dataset.execId = String(msg.id);
    openCaptures[msg.target] = { id: msg.id, slot, el: capture, attached: false };
    setHolder(slot, true);
    term.scrollTop = term.scrollHeight;
  }

  function onExecEnd(msg) {
    const recorded = recordExecEnd(msg);
    const open = openCaptures[msg.target];
    if (!open || open.id !== msg.id) {
      const slot = targetToSlot[msg.target];
      if (recorded && slot) setHolder(slot, false);
      return;
    }
    const foot = document.createElement("div");
    foot.className = "cap-foot";
    foot.textContent = sealCopy(msg);
    open.el.appendChild(foot);
    open.el.className = "capture sealed";
    delete openCaptures[msg.target];
    setHolder(open.slot, false);
  }

  function appendLine(target, direction, text, who, tstamp) {
    if (direction === ">>>" && who === "agent" && !openCaptures[target]) {
      recordAgentSend(target, text, tstamp);
    }
    const slot = targetToSlot[target] || SLOT_KEYS[0];
    const el = terms[slot];
    if (!el) return;
    const row = document.createElement("div");
    let cls = "ln dev";
    let prefix = "";
    if (direction === ">>>") {
      if (who === "agent") {
        cls = "ln agent";
        prefix = "◆ agent  ";
      } else {
        cls = "ln op";
        prefix = "▲ you  ";
      }
    } else if (direction === "---") {
      cls = "ln sys";
    }
    row.className = cls;
    const stamp = document.createElement("span");
    stamp.className = "t";
    stamp.textContent = tstamp || "";
    const body = document.createElement("span");
    body.className = "b";
    if (prefix) body.appendChild(document.createTextNode(prefix));
    AnsiRender.renderAnsi(body, text);
    row.append(stamp, body);
    const capture = direction === "<<<" ? openCaptures[target] : null;
    if (capture && !capture.attached) {
      el.appendChild(capture.el);
      capture.attached = true;
      registerCapture(capture.id, capture.el);
    }
    (capture ? capture.el : el).appendChild(row);
    termLineCounts.set(el, (termLineCounts.get(el) || 0) + 1);
    trimTerm(el);
    el.scrollTop = el.scrollHeight;
  }

  function connect() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    ws = new WebSocket(`${proto}://${location.host}/ws`);
    ws.onopen = () => {
      setPill("WS linked", "ok");
      setWsLamp("live");
      return hydrateAgentLog();
    };
    ws.onclose = () => {
      setPill("WS dropped · retry", "warn");
      setWsLamp("warn");
      setTimeout(connect, 1200);
    };
    ws.onerror = () => {
      setPill("WS error", "err");
      setWsLamp("err");
    };
    ws.onmessage = (ev) => {
      let msg;
      try { msg = JSON.parse(ev.data); } catch { return; }
      if (msg.type === "status" || (msg.mode && msg.ports)) applyStatus(msg);
      if (msg.type === "line") appendLine(msg.target, msg.direction, msg.text, msg.who, msg.ts);
      if (msg.type === "exec" && msg.phase === "start") onExecStart(msg);
      if (msg.type === "exec" && msg.phase === "end") onExecEnd(msg);
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
    termLineCounts.set(terms.slot0, 0);
    termLineCounts.set(terms.slot1, 0);
    for (const target of Object.keys(openCaptures)) {
      delete openCaptures[target];
    }
    clearCaptureIndex();
    for (const slot of SLOT_KEYS) {
      setHolder(slot, false);
    }
  });

  connect();
  hydrateAgentLog();
  fetch("/api/status")
    .then((r) => r.json())
    .then(applyStatus)
    .then(refreshPorts);
})();

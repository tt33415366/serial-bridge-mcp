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
  const liveDepthStops = {
    500: document.getElementById("live-depth-500"),
    5000: document.getElementById("live-depth-5000"),
    75000: document.getElementById("live-depth-75000"),
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
  const windowCounts = Object.fromEntries(SLOT_KEYS.map((slot) => [slot, 0]));
  const rowCapture = new WeakMap();
  let jumpFlashTimer = null;
  let jumpNodeTimer = null;
  let jumpNodeMarked = null;
  const FOLLOWED_WINDOW_ENTRY_LIMIT = 240;
  const LIVE_TAIL_TOLERANCE_PX = 32;
  const OMITTED_TAIL_LIMIT = 32;
  const OMITTED_WRITE_LIMIT = 200;
  const ESTIMATED_ROW_HEIGHT_PX = 18;
  const HISTORY_REWINDOW_MARGIN_PX = 300;
  let retainedLineSequence = 0;
  const followState = Object.fromEntries(
    SLOT_KEYS.map((slot) => [slot, { following: true, evicted: 0, tail: [], writes: [] }])
  );
  const historyStates = Object.fromEntries(SLOT_KEYS.map((slot) => [slot, null]));

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

  const LIVE_VIEW_BUDGET_KEY = "serial-bridge-live-view-budget";
  const LIVE_VIEW_BUDGETS = [500, 5000, 75000];
  const DEFAULT_LIVE_VIEW_BUDGET = 75000;

  function normalizeLiveViewBudget(value) {
    const budget = Number(value);
    return LIVE_VIEW_BUDGETS.includes(budget) ? budget : DEFAULT_LIVE_VIEW_BUDGET;
  }

  let liveViewBudget = normalizeLiveViewBudget(localStorage.getItem(LIVE_VIEW_BUDGET_KEY));

  const paneModels = Object.fromEntries(
    SLOT_KEYS.map((slot) => [slot, TranscriptView.createPane(liveViewBudget)])
  );

  function updateLiveDepthInstrument() {
    for (const budget of LIVE_VIEW_BUDGETS) {
      const stop = liveDepthStops[budget];
      const active = budget === liveViewBudget;
      stop.classList.toggle("active", active);
      stop.setAttribute("aria-pressed", String(active));
    }
  }

  function setLiveViewBudget(value) {
    const budget = Number(value);
    if (!LIVE_VIEW_BUDGETS.includes(budget)) return;
    liveViewBudget = budget;
    localStorage.setItem(LIVE_VIEW_BUDGET_KEY, String(budget));
    updateLiveDepthInstrument();
    for (const slot of SLOT_KEYS) {
      paneModels[slot].setBudget(budget);
      if (historyStates[slot]) rebuildHistoryIndex(slot);
      else trimFollowedWindow(slot);
    }
  }

  function hasClass(el, name) {
    return String(el.className || "").split(" ").includes(name);
  }

  /**
   * The Live View Budget is model retention; the followed window is what the browser has
   * to lay out, hit-test and paint on every keystroke, so it stays far smaller. A budget
   * below the window would make the window the tighter of the two.
   */
  function followedWindowLimit() {
    return Math.min(FOLLOWED_WINDOW_ENTRY_LIMIT, liveViewBudget);
  }

  function setCaptureRowEdges(row, top, bottom) {
    row.classList.remove("cap-top", "cap-mid", "cap-bot");
    if (top) row.classList.add("cap-top");
    if (bottom) row.classList.add("cap-bot");
    if (!top && !bottom) row.classList.add("cap-mid");
  }

  /**
   * The head of the window must still read as a self-contained capture: a footer whose
   * rows have all been trimmed away is an orphan, and the surviving first row of a
   * still-visible capture takes over both the top rule and the Trace Jump anchor.
   */
  function normalizeWindowHead(el) {
    let head = el.firstElementChild;
    while (head && hasClass(head, "cap-foot")) {
      forgetTrimmedRow(head);
      el.removeChild(head);
      head = el.firstElementChild;
    }
    if (!head || !hasClass(head, "capture-row") || hasClass(head, "cap-top")) return;
    setCaptureRowEdges(head, true, hasClass(head, "cap-bot"));
    const record = rowCapture.get(head);
    if (record) captureIndex.set(record.id, head);
  }

  function forgetTrimmedRow(row) {
    const record = rowCapture.get(row);
    if (!record) return;
    if (record.lastRow === row) record.lastRow = null;
    if (record.footRow === row) record.footRow = null;
    if (captureIndex.get(record.id) === row) captureIndex.delete(record.id);
  }

  function trimFollowedWindow(slot) {
    if (historyStates[slot]) return;
    const el = terms[slot];
    const limit = followedWindowLimit();
    while (windowCounts[slot] > limit) {
      const row = el.firstElementChild;
      if (!row) break;
      forgetTrimmedRow(row);
      el.removeChild(row);
      if (hasClass(row, "ln")) windowCounts[slot] -= 1;
      normalizeWindowHead(el);
    }
  }

  function countWindowRow(slot) {
    windowCounts[slot] += 1;
    trimFollowedWindow(slot);
  }

  const overflowProbes = [];

  /**
   * Whether a row's text actually overflows its three-line cap is only knowable from
   * layout, so rows are probed together in the frame after they are appended: all reads
   * first, then the affordance writes. Rows already trimmed out of the window are
   * skipped, which keeps the probe bounded by the window instead of by the burst.
   */
  function queueOverflowProbe(row, body) {
    overflowProbes.push({ row, body });
    if (overflowProbes.length > FOLLOWED_WINDOW_ENTRY_LIMIT * 4) {
      overflowProbes.splice(0, overflowProbes.length - FOLLOWED_WINDOW_ENTRY_LIMIT);
    }
  }

  function flushOverflowProbes() {
    const overflowed = [];
    for (const probe of overflowProbes) {
      if (!probe.row.parentNode) continue;
      if (probe.body.scrollHeight > probe.body.clientHeight) overflowed.push(probe.row);
    }
    overflowProbes.length = 0;
    for (const row of overflowed) addExpandAffordance(row);
  }

  function addExpandAffordance(row) {
    if (hasClass(row, "clamped")) return;
    row.classList.add("clamped");
    const toggle = document.createElement("button");
    toggle.className = "ln-expand";
    toggle.setAttribute("type", "button");
    toggle.setAttribute("aria-expanded", "false");
    toggle.setAttribute("aria-label", "Show the full line");
    toggle.textContent = "⋯";
    row.appendChild(toggle);
  }

  function toggleRowExpansion(toggle) {
    const row = toggle.parentNode;
    if (!row) return;
    const expanded = !hasClass(row, "expanded");
    row.classList.toggle("expanded", expanded);
    toggle.setAttribute("aria-expanded", String(expanded));
    toggle.setAttribute("aria-label", expanded ? "Collapse this line" : "Show the full line");
  }

  /** One listener per pane, so 240 rows cost 2 listeners rather than 240. */
  function expandToggleFrom(node, pane) {
    for (let el = node; el && el !== pane; el = el.parentNode) {
      if (typeof el.className === "string" && hasClass(el, "ln-expand")) return el;
    }
    return null;
  }

  function isNearLiveTail(el) {
    return el.scrollHeight - el.clientHeight - el.scrollTop <= LIVE_TAIL_TOLERANCE_PX;
  }

  function formatSpaceGroupedCount(count) {
    return String(count).replace(/\B(?=(\d{3})+(?!\d))/g, " ");
  }

  function transcriptGapCopy(count) {
    return `— ${formatSpaceGroupedCount(count)} lines in session log, not in this view —`;
  }

  function isTranscriptGap(row) {
    return row && hasClass(row, "ln") && hasClass(row, "gap");
  }

  function lastChild(el) {
    const children = el.children;
    return children[children.length - 1] || null;
  }

  function setGapCount(row, count) {
    row.dataset.evictedCount = String(count);
    row.textContent = transcriptGapCopy(count);
  }

  /**
   * The three row shapes a transcript entry can take. Both the followed tail and a
   * detached historical slice build their rows here, so a retained entry looks the same
   * whichever path materialized it.
   */
  function createLineRow(direction, text, who, tstamp) {
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
    queueOverflowProbe(row, body);
    return row;
  }

  function createGapRow(count) {
    const row = document.createElement("div");
    row.className = "ln gap";
    setGapCount(row, count);
    return row;
  }

  function createFootRow(execId, text) {
    const foot = document.createElement("div");
    foot.className = "cap-foot";
    foot.dataset.execId = String(execId);
    foot.textContent = text;
    return foot;
  }

  /**
   * A Gap always keeps its own trailing replay content attached right after it: a Gap is
   * only counted once the retained tail is full, so at least 32 replayed rows follow it,
   * and one recovery appends at most 233 entries (232 retained rows plus the Gap) which
   * still fits the 240-entry window. Window trimming therefore can never split a Gap
   * from what follows it, and two separately-created Gaps can never end up adjacent
   * through normal flow. This merge branch is a defensive guard, not currently
   * reachable — kept in case that invariant ever changes.
   */
  function appendOrMergeTranscriptGap(slot, count) {
    const el = terms[slot];
    paneModels[slot].appendGap(count);
    const prior = lastChild(el);
    if (isTranscriptGap(prior)) {
      setGapCount(prior, (Number(prior.dataset.evictedCount) || 0) + count);
      return;
    }
    el.appendChild(createGapRow(count));
    countWindowRow(slot);
  }

  function rememberOmittedLine(slot, target, direction, text, who, tstamp, options = {}) {
    const state = followState[slot];
    const item = {
      target,
      direction,
      text,
      who,
      tstamp,
      order: retainedLineSequence++,
    };
    if (direction === "<<<") {
      item.capture = options.capture || null;
      state.tail.push(item);
      if (state.tail.length > OMITTED_TAIL_LIMIT) {
        state.tail.shift();
        state.evicted += 1;
      }
      return;
    }
    state.writes.push(item);
    if (state.writes.length > OMITTED_WRITE_LIMIT) {
      state.writes.shift();
      state.evicted += 1;
    }
  }

  function resetFollowState(slot) {
    followState[slot] = { following: true, evicted: 0, tail: [], writes: [] };
  }

  /** Missing timestamps sort as the empty string so every pair has a well-defined, transitive order. */
  function timestampSortValue(value) {
    return value ? String(value) : "";
  }

  function compareRetainedLines(a, b) {
    const aStamp = timestampSortValue(a.tstamp);
    const bStamp = timestampSortValue(b.tstamp);
    if (aStamp !== bStamp) return aStamp < bStamp ? -1 : 1;
    return a.order - b.order;
  }

  /**
   * Row-level capture chrome leaves no wrapper to move, so a capture that is already
   * materialized has its own rows (and footer) relocated after the new Gap. Replay then
   * continues that one run instead of opening a visually separate second box below the
   * Gap.
   *
   * Retention is reordered in the same breath, and unconditionally: it is the authority on
   * visual order and the thing a later detach renders from, so a capture whose rows are
   * currently off-window still has to end up where the operator just saw it.
   */
  function moveCaptureRowsAfterGap(slot, record) {
    paneModels[slot].moveCaptureToEnd(record.id);
    const el = terms[slot];
    const rows = [];
    for (let child = el.firstElementChild; child; child = child.nextElementSibling) {
      if (rowCapture.get(child) === record) rows.push(child);
    }
    if (!rows.length) return;
    for (const row of rows) {
      el.removeChild(row);
      el.appendChild(row);
    }
    normalizeWindowHead(el);
  }

  function recoverTranscriptGap(slot) {
    const state = followState[slot];
    const evicted = state.evicted;
    if (!evicted && !state.tail.length && !state.writes.length) return;
    const retained = state.tail.concat(state.writes).sort(compareRetainedLines);
    state.evicted = 0;
    state.tail = [];
    state.writes = [];
    if (evicted > 0) appendOrMergeTranscriptGap(slot, evicted);
    const movedCaptures = new Set();
    retained.forEach((item) => {
      if (item.capture && !movedCaptures.has(item.capture)) {
        moveCaptureRowsAfterGap(slot, item.capture);
        movedCaptures.add(item.capture);
      }
    });
    retained.forEach((item) => {
      appendLine(item.target, item.direction, item.text, item.who, item.tstamp, {
        replaying: true,
        capture: item.capture,
      });
    });
  }

  /**
   * Detached history. A pane that has scrolled off the live tail can be looking anywhere
   * in up to 75k retained entries, so it materializes only the slice under the viewport
   * and represents everything above and below it as a single spacer height each. All the
   * pixel arithmetic goes through a height index, so a scroll costs O(window) DOM work
   * plus O(log retained) lookups — never the retained depth.
   */
  function createSpacer() {
    const spacer = document.createElement("div");
    spacer.className = "transcript-spacer";
    spacer.style.height = "0px";
    return spacer;
  }

  function setSpacerHeight(spacer, px) {
    spacer.style.height = `${px > 0 && isFinite(px) ? Math.round(px) : 0}px`;
  }

  function childElements(from, stop) {
    const rows = [];
    for (let child = from; child && child !== stop; child = child.nextElementSibling) {
      rows.push(child);
    }
    return rows;
  }

  function historyRows(state) {
    return childElements(state.top.nextElementSibling, state.bottom);
  }

  /**
   * Sub-pixel, deliberately: offsetHeight rounds to whole pixels, and a half-pixel error
   * per row accumulates into a visible jump once a couple of hundred rows separate the
   * anchor from the top of the slice.
   */
  function measuredHeight(row) {
    return row.getBoundingClientRect().height;
  }

  function enterHistoryMode(slot) {
    const el = terms[slot];
    const count = paneModels[slot].size();
    const rows = childElements(el.firstElementChild, null);
    // Everything retained is already on screen, so there is no history to virtualize and
    // the pane keeps its plain followed window.
    if (count <= rows.length) return;
    flushOverflowProbes();
    const index = TranscriptView.createHeightIndex(count, ESTIMATED_ROW_HEIGHT_PX);
    const start = count - rows.length;
    rows.forEach((row, i) => index.setHeight(start + i, measuredHeight(row)));
    const offset = index.offsetOf(start);
    const top = createSpacer();
    const bottom = createSpacer();
    setSpacerHeight(top, offset);
    el.insertBefore(top, el.firstElementChild);
    el.appendChild(bottom);
    historyStates[slot] = { index, count, start, end: count, top, bottom };
    // The spacer pushed the visible rows down by exactly its own height, so matching it
    // leaves the Operator looking at the same pixel of the same row.
    el.scrollTop = el.scrollTop + offset;
    scheduleHistoryRender(slot);
  }

  /**
   * Retention can still grow while a pane is detached — a capture sealing appends its
   * footer — and nothing else about the pane may move when it does. Taking the new depth
   * into the index and the bottom spacer is what keeps the virtual bottom one entry
   * further down, so Follow does not reattach at what is no longer the end.
   */
  function syncHistoryCount(slot) {
    const state = historyStates[slot];
    const count = paneModels[slot].size();
    if (count <= state.count) return;
    state.index.grow(count);
    state.count = count;
    setSpacerHeight(state.bottom, state.index.total() - state.index.offsetOf(state.end));
  }

  /**
   * The followed window only ever shows a footer directly under the rows it seals, which
   * `normalizeWindowHead` enforces at the head. A historical slice has to be laxer: it
   * draws one row per retained entry so measurements line up, and retention keeps a
   * capture's footer even after budget trimming took every line it sealed. Adopting such
   * a slice as the followed window is where those strays have to go, otherwise a capture
   * replayed on reattach seals itself twice.
   */
  function dropOrphanedFooters(el) {
    let previous = null;
    for (const row of childElements(el.firstElementChild, null)) {
      const sealsTheRowAbove =
        previous &&
        hasClass(previous, "capture-row") &&
        previous.dataset.execId === row.dataset.execId;
      if (hasClass(row, "cap-foot") && !sealsTheRowAbove) {
        forgetTrimmedRow(row);
        el.removeChild(row);
      } else {
        previous = row;
      }
    }
  }

  function exitHistoryMode(slot) {
    const state = historyStates[slot];
    if (!state) return;
    const el = terms[slot];
    syncHistoryCount(slot);
    // A drag straight to the bottom can reattach from a slice that is not the model tail;
    // the followed window has to be the tail before Follow resumes appending to it.
    if (state.end < state.count) {
      renderHistorySlice(slot, Math.max(0, state.count - followedWindowLimit()));
    }
    el.removeChild(state.top);
    el.removeChild(state.bottom);
    historyStates[slot] = null;
    dropOrphanedFooters(el);
    trimFollowedWindow(slot);
  }

  /**
   * The capture records a pane will still append to, by exec id. A capture is live while
   * `openCaptures` holds it, and stays live after it seals if any omitted row is waiting
   * to replay through it, because that replay continues the same visual run.
   */
  function liveCaptureRecords(slot) {
    const live = new Map();
    for (const record of Object.values(openCaptures)) {
      if (record.slot === slot) live.set(record.id, record);
    }
    for (const item of followState[slot].tail) {
      if (item.capture) live.set(item.capture.id, item.capture);
    }
    return live;
  }

  function clearHistorySlice(slot) {
    const state = historyStates[slot];
    const el = terms[slot];
    for (const row of historyRows(state)) {
      forgetTrimmedRow(row);
      el.removeChild(row);
    }
    windowCounts[slot] = 0;
  }

  /**
   * Capture chrome is derived from the slice rather than from live bookkeeping: a run of
   * consecutive rows sharing a capture id is drawn as one box, so a run cut by either
   * window edge still reads as a self-contained capture. A footer is only drawn where the
   * model actually holds one, which keeps a windowed capture from growing a second seal.
   *
   * Every row a run produces joins `rowCapture` under one record per capture, exactly as
   * `attachCapturedRow` does for a followed row. These rows outlive history mode —
   * reattaching keeps them and the followed window trims them later — so without a record
   * the trimmer cannot retire their Trace Jump anchor or hand it to the next surviving
   * row of the same capture.
   */
  function renderHistorySlice(slot, start) {
    const state = historyStates[slot];
    const el = terms[slot];
    const end = Math.min(state.count, start + followedWindowLimit());
    clearHistorySlice(slot);
    const live = liveCaptureRecords(slot);
    const records = new Map();
    let counted = 0;
    let run = [];
    let runId = null;

    /**
     * A capture that outlives the detach keeps one record, so its rows stay one capture.
     * Minting a private one here would leave recovery holding a different object for the
     * same exec: `moveCaptureRowsAfterGap` would not recognize these rows, replay would
     * open a second box with its own footer, and the anchor would end up on that lower
     * fragment. Otherwise the record only has to carry what the trimmer reads.
     */
    function recordFor(id) {
      let record = records.get(id);
      if (!record) {
        record = live.get(id) || { id, lastRow: null, footRow: null };
        records.set(id, record);
      }
      return record;
    }

    function closeRun() {
      if (!run.length) return;
      const first = !records.has(runId);
      const record = recordFor(runId);
      run.forEach((row, i) => {
        setCaptureRowEdges(row, i === 0, i === run.length - 1);
        rowCapture.set(row, record);
      });
      record.lastRow = run[run.length - 1];
      // The first materialized row wins the anchor, so a capture split by a Gap still
      // jumps to its top rather than to the fragment below the Gap.
      if (first) captureIndex.set(runId, run[0]);
      run = [];
      runId = null;
    }

    for (const entry of paneModels[slot].slice(start, end)) {
      let row;
      if (entry.kind === "gap") {
        closeRun();
        row = createGapRow(entry.count);
        counted += 1;
      } else if (entry.kind === "foot") {
        closeRun();
        row = createFootRow(entry.captureId, entry.text);
        const record = recordFor(entry.captureId);
        record.footRow = row;
        rowCapture.set(row, record);
      } else {
        row = createLineRow(entry.direction, entry.text, entry.who, entry.tstamp);
        counted += 1;
        const captureId = entry.captureId;
        if (captureId === null || captureId === undefined) {
          closeRun();
        } else {
          if (captureId !== runId) closeRun();
          row.classList.add("capture-row");
          row.dataset.execId = String(captureId);
          runId = captureId;
          run.push(row);
        }
      }
      el.insertBefore(row, state.bottom);
    }
    closeRun();
    state.start = start;
    state.end = end;
    windowCounts[slot] = counted;
    setSpacerHeight(state.top, state.index.offsetOf(start));
    setSpacerHeight(state.bottom, state.index.total() - state.index.offsetOf(end));
  }

  /**
   * What the pane must hold still across a re-measure. The entry is clamped into the
   * materialized slice on purpose: an entry that is still on its estimate changes height
   * the moment it is materialized, so anchoring on one would move the very compensation
   * it is supposed to provide. Clamping instead pins the oldest row the Operator can
   * currently see, and everything below it rides along unmoved.
   */
  function historyAnchor(slot) {
    const state = historyStates[slot];
    const scrollTop = terms[slot].scrollTop;
    const last = Math.max(state.start, state.end - 1);
    const index = Math.min(Math.max(state.index.indexAtOffset(scrollTop), state.start), last);
    return { index, offset: scrollTop - state.index.offsetOf(index) };
  }

  function restoreHistoryAnchor(slot, anchor) {
    const state = historyStates[slot];
    terms[slot].scrollTop = state.index.offsetOf(anchor.index) + anchor.offset;
  }

  /**
   * Estimated heights become measured ones here: read every materialized row, then write
   * the index, both spacers and the scroll position together, so the anchor keeps the
   * pixel offset it had before the correction.
   */
  function measureHistorySlice(slot, anchor) {
    const state = historyStates[slot];
    const index = state.index;
    flushOverflowProbes();
    const held = anchor || historyAnchor(slot);
    const measured = historyRows(state).map(measuredHeight);
    measured.forEach((height, i) => index.setHeight(state.start + i, height));
    setSpacerHeight(state.top, index.offsetOf(state.start));
    setSpacerHeight(state.bottom, index.total() - index.offsetOf(state.end));
    restoreHistoryAnchor(slot, held);
  }

  /**
   * The buffer has to outlast a whole viewport of scrolling, otherwise a single fast
   * scroll event can land the viewport past the materialized slice before the frame that
   * would have extended it ever runs.
   */
  function historyNeedsRewindow(state, scrollTop, viewport) {
    const index = state.index;
    const margin = Math.max(HISTORY_REWINDOW_MARGIN_PX, viewport);
    if (state.start > 0 && scrollTop - index.offsetOf(state.start) < margin) return true;
    return (
      state.end < state.count &&
      index.offsetOf(state.end) - (scrollTop + viewport) < margin
    );
  }

  function updateHistoryWindow(slot) {
    const state = historyStates[slot];
    if (!state) return;
    syncHistoryCount(slot);
    const el = terms[slot];
    const scrollTop = el.scrollTop;
    if (!historyNeedsRewindow(state, scrollTop, el.clientHeight)) return;
    const anchor = historyAnchor(slot);
    const limit = followedWindowLimit();
    const centre = state.index.indexAtOffset(scrollTop);
    const start = Math.max(0, Math.min(centre - Math.floor(limit / 2), state.count - limit));
    renderHistorySlice(slot, start);
    restoreHistoryAnchor(slot, anchor);
    measureHistorySlice(slot, anchor);
  }

  /** Tightening retention drops the oldest entries, which shifts every index down by that many. */
  function rebuildHistoryIndex(slot) {
    const state = historyStates[slot];
    const el = terms[slot];
    const count = paneModels[slot].size();
    const dropped = Math.max(0, state.count - count);
    el.scrollTop = Math.max(0, el.scrollTop - state.index.offsetOf(dropped));
    state.index = TranscriptView.createHeightIndex(count, ESTIMATED_ROW_HEIGHT_PX);
    state.count = count;
    renderHistorySlice(
      slot,
      Math.max(0, Math.min(state.start - dropped, count - followedWindowLimit()))
    );
    measureHistorySlice(slot);
  }

  const pendingHistoryRenders = new Set();
  let historyFramePending = false;

  function scheduleHistoryRender(slot) {
    pendingHistoryRenders.add(slot);
    if (historyFramePending) return;
    historyFramePending = true;
    requestAnimationFrame(flushHistoryRenders);
  }

  function flushHistoryRenders() {
    historyFramePending = false;
    const slots = [...pendingHistoryRenders];
    pendingHistoryRenders.clear();
    for (const slot of slots) {
      updateHistoryWindow(slot);
      // Re-windowing can uncover the true virtual bottom without another scroll event.
      if (historyStates[slot]) updateFollowState(slot);
    }
  }

  const pendingScrolls = new Set();
  const lastAutoScrollTarget = new WeakMap();
  let scrollPending = false;

  /**
   * A scroll event is only a stale echo of our own tail-scrolling — safe to ignore —
   * when BOTH: another automatic scroll for this pane is still queued (pendingScrolls),
   * and the pane's current scrollTop is still at or after the position our last
   * automatic scroll actually landed on. Requiring the pending scroll too (not just the
   * target comparison) matters once a target is realistically clamped to the true tail
   * position: a later, genuine reattachment scroll can legitimately land exactly on that
   * same stale target long after the auto-scroll that set it was flushed, and must still
   * be evaluated. A genuine upward user scroll below the target is never swallowed
   * either way, and a pane with no recorded target is never suppressed.
   */
  function updateFollowState(slot) {
    const el = terms[slot];
    if (
      pendingScrolls.has(el) &&
      lastAutoScrollTarget.has(el) &&
      el.scrollTop >= lastAutoScrollTarget.get(el)
    ) {
      return;
    }
    const state = followState[slot];
    const wasFollowing = state.following;
    state.following = isNearLiveTail(el);
    if (wasFollowing && !state.following) {
      // A pane can detach while an automatic scroll from before the detach is
      // still queued. Drop it so the queued flush doesn't drag the pane back
      // to the tail and fire a scroll event that reattaches it right after.
      pendingScrolls.delete(el);
      enterHistoryMode(slot);
    }
    if (!wasFollowing && state.following) {
      exitHistoryMode(slot);
      recoverTranscriptGap(slot);
    }
  }

  function paneIsFollowing(slot) {
    return followState[slot].following;
  }

  /**
   * Real browsers clamp an assigned scrollTop to [0, scrollHeight - clientHeight], so the
   * value that actually lands can be lower than scrollHeight. Assign first, then read the
   * element's own (possibly clamped) scrollTop back, so the recorded target always matches
   * what the pane truly landed on.
   */
  function flushScrolls() {
    scrollPending = false;
    for (const el of pendingScrolls) {
      el.scrollTop = el.scrollHeight;
      lastAutoScrollTarget.set(el, el.scrollTop);
    }
    pendingScrolls.clear();
    flushOverflowProbes();
  }

  function scheduleScroll(el) {
    pendingScrolls.add(el);
    if (scrollPending) return;
    scrollPending = true;
    requestAnimationFrame(flushScrolls);
  }

  function schedulePaneScroll(slot) {
    if (paneIsFollowing(slot)) scheduleScroll(terms[slot]);
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

  function clearCaptureIndex() {
    captureIndex.clear();
  }

  function markJumpNode(node, marker) {
    if (!node) return;
    if (jumpNodeTimer) clearTimeout(jumpNodeTimer);
    if (jumpNodeMarked) jumpNodeMarked.classList.remove("jump-hit", "jump-miss");
    node.classList.remove("jump-hit", "jump-miss");
    node.classList.add(marker);
    jumpNodeMarked = node;
    jumpNodeTimer = setTimeout(() => {
      node.classList.remove(marker);
      jumpNodeMarked = null;
      jumpNodeTimer = null;
    }, 1200);
  }

  function traceJump(execId, node) {
    const el = captureIndex.get(Number(execId));
    if (!el || !captureStillInTerm(el)) {
      markJumpNode(node, "jump-miss");
      return;
    }
    // Positioned without a smooth animation so arrival and the capture highlight coincide;
    // a long animated scroll outlasts the highlight timer below.
    if (typeof el.scrollIntoView === "function") {
      el.scrollIntoView({ block: "nearest" });
    }
    markJumpNode(node, "jump-hit");
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
        node.addEventListener("click", () => traceJump(entry.id, node));
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

  function recordLineSideEffects(target, direction, text, who, tstamp) {
    if (direction === ">>>" && who === "agent" && !openCaptures[target]) {
      recordAgentSend(target, text, tstamp);
    }
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
    if (!terms[slot]) return;
    openCaptures[msg.target] = {
      id: Number(msg.id),
      slot,
      sealed: false,
      footText: "",
      lastRow: null,
      footRow: null,
    };
    setHolder(slot, true);
    schedulePaneScroll(slot);
  }

  function onExecEnd(msg) {
    const recorded = recordExecEnd(msg);
    const open = openCaptures[msg.target];
    if (!open || open.id !== Number(msg.id)) {
      const slot = targetToSlot[msg.target];
      if (recorded && slot) setHolder(slot, false);
      return;
    }
    const text = sealCopy(msg);
    open.sealed = true;
    open.footText = text;
    paneModels[open.slot].appendFoot({ captureId: open.id, text });
    if (historyStates[open.slot]) {
      // A detached pane draws its rows from the retained model, so the footer arrives
      // when the window that holds its position is rendered. Splicing it in here would
      // leave one more row between the spacers than the slice accounts for, and every
      // row below it would then be measured as its neighbour.
      scheduleHistoryRender(open.slot);
    } else if (open.lastRow && open.lastRow.parentNode === terms[open.slot]) {
      setCaptureRowEdges(open.lastRow, hasClass(open.lastRow, "cap-top"), true);
      materializeCaptureFoot(open);
    }
    delete openCaptures[msg.target];
    setHolder(open.slot, false);
  }

  /**
   * The footer trails its own last row, which is not necessarily the pane's last row.
   * Retention is sealed in the same step, and every time: trimming drops a seal once the
   * run it closed is gone, and replay can then bring a row of that capture back, so the
   * model has to hear about the seal again rather than be left holding an unclosed run.
   * Sealing a capture that retention already has one for does nothing.
   */
  function materializeCaptureFoot(record) {
    const el = terms[record.slot];
    paneModels[record.slot].appendFoot({ captureId: record.id, text: record.footText });
    if (record.footRow && record.footRow.parentNode === el) return;
    const foot = createFootRow(record.id, record.footText);
    rowCapture.set(foot, record);
    el.insertBefore(foot, record.lastRow.nextElementSibling);
    record.footRow = foot;
  }

  /**
   * Captured rows join their capture's run rather than the pane's tail, so an Operator
   * write that barged in mid-capture stays below the capture instead of splitting it.
   */
  function attachCapturedRow(record, row) {
    const el = terms[record.slot];
    const previous = record.lastRow && record.lastRow.parentNode === el ? record.lastRow : null;
    row.classList.add("capture-row");
    row.dataset.execId = String(record.id);
    rowCapture.set(row, record);
    setCaptureRowEdges(row, !previous, record.sealed);
    if (previous && hasClass(previous, "cap-bot")) {
      setCaptureRowEdges(previous, hasClass(previous, "cap-top"), false);
    }
    if (record.footRow && record.footRow.parentNode === el) {
      el.insertBefore(row, record.footRow);
    } else if (previous) {
      el.insertBefore(row, previous.nextElementSibling);
    } else {
      el.appendChild(row);
    }
    record.lastRow = row;
    if (!previous) captureIndex.set(record.id, row);
    if (record.sealed) materializeCaptureFoot(record);
  }

  function appendLine(target, direction, text, who, tstamp, options = {}) {
    if (!options.replaying) {
      recordLineSideEffects(target, direction, text, who, tstamp);
    }
    const slot = targetToSlot[target] || SLOT_KEYS[0];
    const el = terms[slot];
    if (!el) return;
    const capture =
      direction === "<<<"
        ? Object.prototype.hasOwnProperty.call(options, "capture")
          ? options.capture
          : openCaptures[target]
        : null;
    const detachable = direction === "<<<" || direction === ">>>" || direction === "---";
    if (detachable && !options.replaying && !paneIsFollowing(slot)) {
      rememberOmittedLine(slot, target, direction, text, who, tstamp, { capture });
      return;
    }
    paneModels[slot].appendLine({
      direction,
      text,
      who,
      tstamp,
      captureId: capture ? capture.id : null,
    });
    const row = createLineRow(direction, text, who, tstamp);
    if (capture) attachCapturedRow(capture, row);
    else el.appendChild(row);
    countWindowRow(slot);
    schedulePaneScroll(slot);
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
      if (msg.type === "line") {
        const items = msg.items || [msg];
        for (const item of items) {
          appendLine(item.target, item.direction, item.text, item.who, item.ts);
        }
      }
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
  for (const budget of LIVE_VIEW_BUDGETS) {
    liveDepthStops[budget].addEventListener("click", () => setLiveViewBudget(budget));
  }
  updateLiveDepthInstrument();

  for (const slot of SLOT_KEYS) {
    terms[slot].addEventListener("scroll", () => {
      updateFollowState(slot);
      if (historyStates[slot]) scheduleHistoryRender(slot);
    });
    terms[slot].addEventListener("click", (event) => {
      const toggle = expandToggleFrom(event.target, terms[slot]);
      if (!toggle) return;
      toggleRowExpansion(toggle);
      // The row just changed height, so the history index and both spacers owe it a
      // correction — without letting the anchor row move under the Operator.
      if (historyStates[slot]) measureHistorySlice(slot);
    });
  }

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
    for (const slot of SLOT_KEYS) {
      terms[slot].innerHTML = "";
      windowCounts[slot] = 0;
      historyStates[slot] = null;
      resetFollowState(slot);
      setHolder(slot, false);
      paneModels[slot].clear();
    }
    overflowProbes.length = 0;
    for (const target of Object.keys(openCaptures)) {
      delete openCaptures[target];
    }
    clearCaptureIndex();
  });

  connect();
  hydrateAgentLog();
  fetch("/api/status")
    .then((r) => r.json())
    .then(applyStatus)
    .then(refreshPorts);
})();

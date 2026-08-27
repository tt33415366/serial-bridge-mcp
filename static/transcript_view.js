(function (root) {
  function isCounted(entry) {
    return entry.kind === "line" || entry.kind === "gap";
  }

  function maybeCompact(state) {
    if (state.start === 0) return;
    if (state.start < 1024 && state.start <= state.list.length / 2) return;
    state.list = state.list.slice(state.start);
    state.start = 0;
  }

  function dropOldestCounted(state) {
    for (let i = state.start; i < state.list.length; i++) {
      if (isCounted(state.list[i])) {
        if (i === state.start) {
          state.start = i + 1;
        } else {
          state.list.splice(i, 1);
        }
        maybeCompact(state);
        return true;
      }
    }
    return false;
  }

  function hasRemainingLine(state, captureId) {
    for (let i = state.start; i < state.list.length; i++) {
      const entry = state.list[i];
      if (entry.kind === "line" && entry.captureId === captureId) return true;
    }
    return false;
  }

  function dropOrphanFeet(state) {
    while (
      state.start < state.list.length &&
      state.list[state.start].kind === "foot" &&
      !hasRemainingLine(state, state.list[state.start].captureId)
    ) {
      state.start += 1;
    }
    maybeCompact(state);
  }

  function trim(state) {
    while (state.counted > state.budget) {
      if (!dropOldestCounted(state)) break;
      state.counted -= 1;
      dropOrphanFeet(state);
    }
  }

  function createPane(budget) {
    const state = { list: [], start: 0, budget, counted: 0 };

    function appendLine(fields) {
      state.list.push({
        kind: "line",
        direction: fields.direction,
        text: fields.text,
        who: fields.who,
        tstamp: fields.tstamp,
        captureId: fields.captureId ?? null,
      });
      state.counted += 1;
      trim(state);
    }

    function appendGap(count) {
      const last = state.list[state.list.length - 1];
      if (last && last.kind === "gap") {
        last.count += count;
      } else {
        state.list.push({ kind: "gap", count });
        state.counted += 1;
      }
      trim(state);
    }

    function appendFoot(fields) {
      state.list.push({
        kind: "foot",
        captureId: fields.captureId ?? null,
        text: fields.text,
      });
    }

    function setBudget(n) {
      state.budget = n;
      trim(state);
    }

    function clear() {
      state.list = [];
      state.start = 0;
      state.counted = 0;
    }

    function entries() {
      return state.list.slice(state.start);
    }

    function countedSize() {
      return state.counted;
    }

    return { appendLine, appendGap, appendFoot, setBudget, clear, entries, countedSize };
  }

  root.TranscriptView = { createPane };
})(typeof globalThis !== "undefined" ? globalThis : this);

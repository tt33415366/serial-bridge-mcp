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
        const gone = state.list[i];
        if (gone.kind === "line" && gone.captureId !== null) {
          const record = state.captures.get(gone.captureId);
          if (record) {
            record.lines -= 1;
            forgetEmptyCapture(state, gone.captureId, record);
          }
        }
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

  /**
   * What each capture still has retained. It answers "is any of this capture here, and
   * where does its run end" without walking the list, which is what keeps an ordinary
   * line off the scanning path.
   */
  function captureRecord(state, captureId) {
    let record = state.captures.get(captureId);
    if (!record) {
      record = { lines: 0, foot: false };
      state.captures.set(captureId, record);
    }
    return record;
  }

  function forgetEmptyCapture(state, captureId, record) {
    if (record.lines === 0 && !record.foot) state.captures.delete(captureId);
  }

  function hasRemainingLine(state, captureId) {
    const record = state.captures.get(captureId);
    return Boolean(record && record.lines > 0);
  }

  function dropOrphanFeet(state) {
    while (
      state.start < state.list.length &&
      state.list[state.start].kind === "foot" &&
      !hasRemainingLine(state, state.list[state.start].captureId)
    ) {
      const captureId = state.list[state.start].captureId;
      const record = state.captures.get(captureId);
      if (record) {
        record.foot = false;
        forgetEmptyCapture(state, captureId, record);
      }
      state.start += 1;
    }
    maybeCompact(state);
  }

  /**
   * Where a capture's next entry belongs: the end of that capture's own run, which is
   * above its seal if it has one. Ordinarily the run is already the tail and this is a
   * couple of comparisons; only a row that barged in behind the capture — an Operator
   * write, a system notice, another target's output — pushes it off the tail and makes
   * the run worth looking for.
   */
  function runEndIndex(state, captureId) {
    const end = state.list.length;
    const last = end > state.start ? state.list[end - 1] : null;
    if (last && last.captureId === captureId) {
      if (last.kind === "line") return end;
      if (last.kind === "foot") return end - 1;
    }
    if (!state.captures.has(captureId)) return end;
    for (let i = end - 1; i >= state.start; i--) {
      const entry = state.list[i];
      if (entry.captureId !== captureId) continue;
      if (entry.kind === "line") return i + 1;
      if (entry.kind === "foot") return i;
    }
    return end;
  }

  function insertAt(state, index, entry) {
    if (index >= state.list.length) state.list.push(entry);
    else state.list.splice(index, 0, entry);
  }

  function trim(state) {
    while (state.counted > state.budget) {
      if (!dropOldestCounted(state)) break;
      state.counted -= 1;
      dropOrphanFeet(state);
    }
  }

  function createPane(budget) {
    const state = { list: [], start: 0, budget, counted: 0, captures: new Map() };

    /**
     * A captured line joins its own capture's run rather than the list tail, so a write
     * or a system notice that barged in mid-capture stays below the whole box and a line
     * that arrives after the capture sealed lands above the seal. That is what the pane
     * has always drawn, and retention is what redraws it after the rows are gone.
     */
    function appendLine(fields) {
      const captureId = fields.captureId ?? null;
      const entry = {
        kind: "line",
        direction: fields.direction,
        text: fields.text,
        who: fields.who,
        tstamp: fields.tstamp,
        captureId,
      };
      insertAt(
        state,
        captureId === null ? state.list.length : runEndIndex(state, captureId),
        entry,
      );
      if (captureId !== null) captureRecord(state, captureId).lines += 1;
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

    /**
     * The seal closes its own run, so it goes directly under that capture's last line
     * rather than under whatever happens to be at the tail. A capture seals once; a
     * repeat is ignored rather than drawn twice. A capture whose lines are all trimmed
     * away has no run to close, and its seal waits at the tail for trimming to reach it.
     */
    function appendFoot(fields) {
      const captureId = fields.captureId ?? null;
      const record = captureRecord(state, captureId);
      if (record.foot) return;
      insertAt(state, runEndIndex(state, captureId), {
        kind: "foot",
        captureId,
        text: fields.text,
      });
      record.foot = true;
    }

    /**
     * Recovery puts a Transcript Gap in front of a capture the operator can already see,
     * and the retained entries have to follow it: every line of that capture still held,
     * and its seal, move to the tail keeping their relative order. Retention is what a
     * later detach renders from, so leaving it in arrival order would show a different
     * transcript the second time the operator scrolls back over the same region. This is
     * the one reordering the model allows, and it costs the retained depth — affordable
     * during recovery, which is why no live line may reach it.
     */
    function moveCaptureToEnd(captureId) {
      if (captureId === null || captureId === undefined) return;
      const kept = [];
      const moved = [];
      for (let i = state.start; i < state.list.length; i++) {
        const entry = state.list[i];
        const mine =
          (entry.kind === "line" || entry.kind === "foot") && entry.captureId === captureId;
        (mine ? moved : kept).push(entry);
      }
      if (!moved.length) return;
      state.list = kept.concat(moved);
      state.start = 0;
      // The move can leave a different capture's seal stranded at the head.
      dropOrphanFeet(state);
    }

    function setBudget(n) {
      state.budget = n;
      trim(state);
    }

    function clear() {
      state.list = [];
      state.start = 0;
      state.counted = 0;
      state.captures.clear();
    }

    function entries() {
      return state.list.slice(state.start);
    }

    function size() {
      return state.list.length - state.start;
    }

    /** Oldest-first index range, so a detached pane can read a window without copying all of it. */
    function slice(from, to) {
      const begin = state.start + Math.max(0, from);
      const finish = state.start + Math.min(size(), Math.max(0, to));
      return finish > begin ? state.list.slice(begin, finish) : [];
    }

    function countedSize() {
      return state.counted;
    }

    return {
      appendLine,
      appendGap,
      appendFoot,
      moveCaptureToEnd,
      setBudget,
      clear,
      entries,
      size,
      slice,
      countedSize,
    };
  }

  /**
   * Row heights for a retained transcript, as a Fenwick tree seeded with one estimate per
   * entry. A detached pane needs three answers — the pixel offset of an entry, the entry
   * covering a pixel, and a correction once a row has actually been measured — and all
   * three stay O(log n), so scrolling never costs the retained depth.
   */
  function createHeightIndex(count, estimate) {
    let size = Math.max(0, Math.floor(count) || 0);
    const base = estimate > 0 ? estimate : 1;
    let heights = new Float64Array(size);
    let tree = new Float64Array(size + 1);
    heights.fill(base);
    for (let i = 1; i <= size; i++) tree[i] = base * (i & -i);

    function offsetOf(index) {
      let i = Math.min(Math.max(index, 0), size);
      let sum = 0;
      for (; i > 0; i -= i & -i) sum += tree[i];
      return sum;
    }

    function setHeight(index, px) {
      if (index < 0 || index >= size) return;
      if (!(px > 0) || !isFinite(px)) return;
      const delta = px - heights[index];
      heights[index] = px;
      for (let i = index + 1; i <= size; i += i & -i) tree[i] += delta;
    }

    function heightAt(index) {
      return index >= 0 && index < size ? heights[index] : 0;
    }

    /** The entry covering `px`, i.e. the last one whose start offset is at or before it. */
    function indexAtOffset(px) {
      let remaining = px;
      if (!(remaining > 0)) return 0;
      let index = 0;
      let step = 1;
      while (step * 2 <= size) step *= 2;
      for (; step > 0; step >>= 1) {
        const next = index + step;
        if (next <= size && tree[next] <= remaining) {
          index = next;
          remaining -= tree[next];
        }
      }
      return Math.min(index, Math.max(size - 1, 0));
    }

    /**
     * Retention only ever appends while a pane is reading history — a capture sealing
     * adds its footer — so growth keeps every height already measured and seeds the new
     * entries at the estimate. Rebuilding instead would drop those measurements and move
     * the very rows the operator is looking at.
     */
    function grow(nextCount) {
      const next = Math.floor(nextCount) || 0;
      if (next <= size) return;
      const grown = new Float64Array(next);
      grown.set(heights);
      grown.fill(base, size);
      heights = grown;
      size = next;
      tree = new Float64Array(size + 1);
      for (let i = 1; i <= size; i++) {
        tree[i] += heights[i - 1];
        const parent = i + (i & -i);
        if (parent <= size) tree[parent] += tree[i];
      }
    }

    return {
      size: () => size,
      total: () => offsetOf(size),
      offsetOf,
      setHeight,
      heightAt,
      indexAtOffset,
      grow,
    };
  }

  root.TranscriptView = { createPane, createHeightIndex };
})(typeof globalThis !== "undefined" ? globalThis : this);

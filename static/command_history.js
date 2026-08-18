(function (root) {
  const STORAGE_PREFIX = "serial-bridge.command-history.";
  const MAX_ENTRIES = 2000;

  function storageKey(slot) {
    return STORAGE_PREFIX + slot;
  }

  function parseHistory(raw) {
    if (!raw) return [];
    try {
      const parsed = JSON.parse(raw);
      if (!Array.isArray(parsed)) return [];
      return parsed.filter((entry) => typeof entry === "string");
    } catch {
      return [];
    }
  }

  function loadHistory(storage, slot) {
    return parseHistory(storage.getItem(storageKey(slot)));
  }

  function saveHistory(storage, slot, history) {
    storage.setItem(storageKey(slot), JSON.stringify(history));
  }

  function recordCommand(history, cmd) {
    const trimmed = cmd.trim();
    if (!trimmed) return history;
    const next = history.slice();
    if (next.length > 0 && next[next.length - 1] === trimmed) {
      return next;
    }
    next.push(trimmed);
    if (next.length > MAX_ENTRIES) {
      return next.slice(next.length - MAX_ENTRIES);
    }
    return next;
  }

  function matchesForPrefix(history, prefix) {
    const filtered = history.filter((entry) => prefix === "" || entry.startsWith(prefix));
    return filtered.slice().reverse();
  }

  function createBrowser(history) {
    let draft = null;
    let activePrefix = "";
    let position = -1;
    let lastShown = null;

    function reset() {
      draft = null;
      activePrefix = "";
      position = -1;
      lastShown = null;
    }

    function currentMatches() {
      return matchesForPrefix(history, activePrefix);
    }

    function arrowUp(currentValue) {
      if (draft === null) {
        draft = currentValue;
        activePrefix = currentValue;
        const matches = currentMatches();
        if (matches.length === 0) {
          reset();
          return { value: currentValue, changed: false };
        }
        position = 0;
        lastShown = matches[0];
        return { value: lastShown, changed: true };
      }

      if (lastShown !== null && currentValue !== lastShown) {
        activePrefix = currentValue;
        const matches = currentMatches();
        if (matches.length === 0) {
          return { value: currentValue, changed: false };
        }
        position = 0;
        lastShown = matches[0];
        return { value: lastShown, changed: true };
      }

      const matches = currentMatches();
      if (matches.length === 0) {
        return { value: currentValue, changed: false };
      }
      if (position < matches.length - 1) {
        position += 1;
        lastShown = matches[position];
        return { value: lastShown, changed: true };
      }
      return { value: lastShown, changed: false };
    }

    function arrowDown(currentValue) {
      if (draft === null) {
        return { value: currentValue, changed: false };
      }

      const matches = currentMatches();
      if (position > 0) {
        position -= 1;
        lastShown = matches[position];
        return { value: lastShown, changed: true };
      }

      const restored = draft;
      reset();
      return { value: restored, changed: true };
    }

    return { arrowUp, arrowDown, reset };
  }

  root.CommandHistory = {
    STORAGE_PREFIX,
    MAX_ENTRIES,
    storageKey,
    loadHistory,
    saveHistory,
    recordCommand,
    matchesForPrefix,
    createBrowser,
  };
})(typeof globalThis !== "undefined" ? globalThis : this);

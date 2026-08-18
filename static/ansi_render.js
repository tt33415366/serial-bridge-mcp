(function (root) {
  const ANSI_SEQUENCE =
    /\x1b\[([\d;]*)m|\x1b\][^\x07]*(?:\x07|\x1b\\)|\x1b\[[0-?]*[ -\/]*[@-~]|\x1b[@-Z\\-_]/g;
  const CUBE_LEVELS = [0, 95, 135, 175, 215, 255];

  function baseStyle() {
    return { fg: null, bg: null, bold: false, dim: false, underline: false, inverse: false };
  }

  function indexedColor(index) {
    if (index < 16) return `var(--ansi-${index})`;
    if (index < 232) {
      const value = index - 16;
      const r = CUBE_LEVELS[Math.floor(value / 36)];
      const g = CUBE_LEVELS[Math.floor(value / 6) % 6];
      const b = CUBE_LEVELS[value % 6];
      return `rgb(${r}, ${g}, ${b})`;
    }
    const gray = 8 + (index - 232) * 10;
    return `rgb(${gray}, ${gray}, ${gray})`;
  }

  function extendedColor(codes, at) {
    if (codes[at + 1] === 5) return { color: indexedColor(codes[at + 2] || 0), next: at + 2 };
    if (codes[at + 1] === 2) {
      const [r, g, b] = [codes[at + 2] || 0, codes[at + 3] || 0, codes[at + 4] || 0];
      return { color: `rgb(${r}, ${g}, ${b})`, next: at + 4 };
    }
    return { color: null, next: at + 1 };
  }

  function applySgr(style, params) {
    const codes = params === "" ? [0] : params.split(";").map((p) => Number(p) || 0);
    const next = { ...style };
    for (let i = 0; i < codes.length; i++) {
      const code = codes[i];
      if (code === 0) Object.assign(next, baseStyle());
      else if (code === 1) next.bold = true;
      else if (code === 2) next.dim = true;
      else if (code === 4) next.underline = true;
      else if (code === 7) next.inverse = true;
      else if (code === 22) { next.bold = false; next.dim = false; }
      else if (code === 24) next.underline = false;
      else if (code === 27) next.inverse = false;
      else if (code === 39) next.fg = null;
      else if (code === 49) next.bg = null;
      else if (code >= 30 && code <= 37) next.fg = `var(--ansi-${code - 30})`;
      else if (code >= 40 && code <= 47) next.bg = `var(--ansi-${code - 40})`;
      else if (code >= 90 && code <= 97) next.fg = `var(--ansi-${code - 82})`;
      else if (code >= 100 && code <= 107) next.bg = `var(--ansi-${code - 92})`;
      else if (code === 38 || code === 48) {
        const extended = extendedColor(codes, i);
        if (code === 38) next.fg = extended.color;
        else next.bg = extended.color;
        i = extended.next;
      }
    }
    return next;
  }

  function snapshotStyle(style) {
    return { ...style };
  }

  function parseSegments(text) {
    let style = baseStyle();
    let cursor = 0;
    let match;
    const segments = [];
    ANSI_SEQUENCE.lastIndex = 0;
    while ((match = ANSI_SEQUENCE.exec(text)) !== null) {
      if (match.index > cursor) {
        segments.push({ text: text.slice(cursor, match.index), style: snapshotStyle(style) });
      }
      cursor = match.index + match[0].length;
      if (match[1] !== undefined) style = applySgr(style, match[1]);
    }
    if (cursor < text.length) {
      segments.push({ text: text.slice(cursor), style: snapshotStyle(style) });
    }
    return segments;
  }

  function styledNode(text, style) {
    const plain =
      !style.fg && !style.bg && !style.bold && !style.dim && !style.underline && !style.inverse;
    if (plain) return document.createTextNode(text);
    const span = document.createElement("span");
    span.textContent = text;
    span.style.color = style.inverse ? style.bg || "var(--ink)" : style.fg || "";
    span.style.background = style.inverse ? style.fg || "currentColor" : style.bg || "";
    if (style.bold) span.style.fontWeight = "600";
    if (style.dim) span.style.opacity = "0.7";
    if (style.underline) span.style.textDecoration = "underline";
    return span;
  }

  function renderAnsi(container, text) {
    for (const segment of parseSegments(text)) {
      container.appendChild(styledNode(segment.text, segment.style));
    }
  }

  root.AnsiRender = {
    ANSI_SEQUENCE,
    baseStyle,
    indexedColor,
    applySgr,
    parseSegments,
    styledNode,
    renderAnsi,
  };
})(typeof globalThis !== "undefined" ? globalThis : this);

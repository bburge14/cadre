/* Shared interactive-terminal connection logic -- used by both the
   inline toggle on session_detail.html and the dedicated full-page
   terminal view. Handles token fetch, WebSocket connect, and automatic
   reconnect with capped exponential backoff, so a dropped connection
   (mobile network switch, tab backgrounded, a brief daemon restart)
   recovers on its own instead of just sitting there disconnected. */

/* The "terminal theme" setting (dark/light/auto) only ever wrote to the
   CLI's own config file -- it never touched xterm.js itself, which every
   call site hardcoded to a plain black background regardless. xterm.js
   is a browser-rendered emulator we fully control ourselves (not the
   user's native terminal app), so there's no OS-specific command needed
   here -- just give it a real theme object. "auto" follows the browser's
   own light/dark preference since there's no OS-level signal otherwise
   meaningful to a terminal running inside a web page. */
const XTERM_THEMES = {
  dark: {
    background: "#000000", foreground: "#e0e0e0", cursor: "#e0e0e0",
    black: "#000000", red: "#e06c75", green: "#98c379", yellow: "#e5c07b",
    blue: "#61afef", magenta: "#c678dd", cyan: "#56b6c2", white: "#dcdfe4",
    brightBlack: "#5c6370", brightRed: "#e06c75", brightGreen: "#98c379",
    brightYellow: "#e5c07b", brightBlue: "#61afef", brightMagenta: "#c678dd",
    brightCyan: "#56b6c2", brightWhite: "#ffffff",
  },
  light: {
    background: "#ffffff", foreground: "#383a42", cursor: "#383a42",
    black: "#383a42", red: "#e45649", green: "#50a14f", yellow: "#c18401",
    blue: "#4078f2", magenta: "#a626a4", cyan: "#0184bc", white: "#fafafa",
    brightBlack: "#a0a1a7", brightRed: "#e45649", brightGreen: "#50a14f",
    brightYellow: "#c18401", brightBlue: "#4078f2", brightMagenta: "#a626a4",
    brightCyan: "#0184bc", brightWhite: "#ffffff",
  },
  // Standard, widely-recognized named palettes -- these are Cadre's own
  // rendering, always correct regardless of which CLI is running inside
  // (terminal_theme.py separately best-effort-maps each of these onto
  // that CLI's own native theme catalog, for anyone using native Remote
  // Control outside this dashboard -- but what's actually drawn here
  // never depends on that mapping existing).
  dracula: {
    background: "#282a36", foreground: "#f8f8f2", cursor: "#f8f8f2",
    black: "#21222c", red: "#ff5555", green: "#50fa7b", yellow: "#f1fa8c",
    blue: "#bd93f9", magenta: "#ff79c6", cyan: "#8be9fd", white: "#f8f8f2",
    brightBlack: "#6272a4", brightRed: "#ff6e6e", brightGreen: "#69ff94",
    brightYellow: "#ffffa5", brightBlue: "#d6acff", brightMagenta: "#ff92df",
    brightCyan: "#a4ffff", brightWhite: "#ffffff",
  },
  "solarized-dark": {
    background: "#002b36", foreground: "#839496", cursor: "#839496",
    black: "#073642", red: "#dc322f", green: "#859900", yellow: "#b58900",
    blue: "#268bd2", magenta: "#d33682", cyan: "#2aa198", white: "#eee8d5",
    brightBlack: "#002b36", brightRed: "#cb4b16", brightGreen: "#586e75",
    brightYellow: "#657b83", brightBlue: "#839496", brightMagenta: "#6c71c4",
    brightCyan: "#93a1a1", brightWhite: "#fdf6e3",
  },
  "solarized-light": {
    background: "#fdf6e3", foreground: "#657b83", cursor: "#657b83",
    black: "#073642", red: "#dc322f", green: "#859900", yellow: "#b58900",
    blue: "#268bd2", magenta: "#d33682", cyan: "#2aa198", white: "#eee8d5",
    brightBlack: "#002b36", brightRed: "#cb4b16", brightGreen: "#586e75",
    brightYellow: "#657b83", brightBlue: "#839496", brightMagenta: "#6c71c4",
    brightCyan: "#93a1a1", brightWhite: "#fdf6e3",
  },
  nord: {
    background: "#2e3440", foreground: "#d8dee9", cursor: "#d8dee9",
    black: "#3b4252", red: "#bf616a", green: "#a3be8c", yellow: "#ebcb8b",
    blue: "#81a1c1", magenta: "#b48ead", cyan: "#88c0d0", white: "#e5e9f0",
    brightBlack: "#4c566a", brightRed: "#bf616a", brightGreen: "#a3be8c",
    brightYellow: "#ebcb8b", brightBlue: "#81a1c1", brightMagenta: "#b48ead",
    brightCyan: "#8fbcbb", brightWhite: "#eceff4",
  },
  monokai: {
    background: "#272822", foreground: "#f8f8f2", cursor: "#f8f8f0",
    black: "#272822", red: "#f92672", green: "#a6e22e", yellow: "#f4bf75",
    blue: "#66d9ef", magenta: "#ae81ff", cyan: "#a1efe4", white: "#f8f8f2",
    brightBlack: "#75715e", brightRed: "#f92672", brightGreen: "#a6e22e",
    brightYellow: "#f4bf75", brightBlue: "#66d9ef", brightMagenta: "#ae81ff",
    brightCyan: "#a1efe4", brightWhite: "#f9f8f5",
  },
  "gruvbox-dark": {
    background: "#282828", foreground: "#ebdbb2", cursor: "#ebdbb2",
    black: "#282828", red: "#cc241d", green: "#98971a", yellow: "#d79921",
    blue: "#458588", magenta: "#b16286", cyan: "#689d6a", white: "#a89984",
    brightBlack: "#928374", brightRed: "#fb4934", brightGreen: "#b8bb26",
    brightYellow: "#fabd2f", brightBlue: "#83a598", brightMagenta: "#d3869b",
    brightCyan: "#8ec07c", brightWhite: "#ebdbb2",
  },
  "tokyo-night": {
    background: "#1a1b26", foreground: "#c0caf5", cursor: "#c0caf5",
    black: "#15161e", red: "#f7768e", green: "#9ece6a", yellow: "#e0af68",
    blue: "#7aa2f7", magenta: "#bb9af7", cyan: "#7dcfff", white: "#a9b1d6",
    brightBlack: "#414868", brightRed: "#f7768e", brightGreen: "#9ece6a",
    brightYellow: "#e0af68", brightBlue: "#7aa2f7", brightMagenta: "#bb9af7",
    brightCyan: "#7dcfff", brightWhite: "#c0caf5",
  },
  "one-dark": {
    background: "#282c34", foreground: "#abb2bf", cursor: "#abb2bf",
    black: "#282c34", red: "#e06c75", green: "#98c379", yellow: "#e5c07b",
    blue: "#61afef", magenta: "#c678dd", cyan: "#56b6c2", white: "#abb2bf",
    brightBlack: "#5c6370", brightRed: "#e06c75", brightGreen: "#98c379",
    brightYellow: "#e5c07b", brightBlue: "#61afef", brightMagenta: "#c678dd",
    brightCyan: "#56b6c2", brightWhite: "#ffffff",
  },
};

function resolveXtermTheme(choice) {
  if (choice === "auto") {
    const prefersLight = window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches;
    return prefersLight ? XTERM_THEMES.light : XTERM_THEMES.dark;
  }
  return XTERM_THEMES[choice] || XTERM_THEMES.dark;
}

// The wrapper div around the terminal (padding + any leftover space
// past however many rows/cols actually fit) has its own background,
// separate from xterm.js's own canvas -- without this, a light theme
// only recolors the terminal's populated rows, leaving a black band of
// unstyled wrapper showing everywhere else.
function syncTerminalWrapperBackground(wrapperId, theme) {
  const el = document.getElementById(wrapperId);
  if (el) el.style.background = theme.background;
}

function createTerminalConnection(sessionId, opts) {
  const { tokenUrl, csrfToken, term, onStatus, onNotRunning } = opts;
  let ws = null;
  let reconnectAttempt = 0;
  let reconnectTimer = null;
  let manuallyClosed = false;

  // Every outgoing message is tagged with a 1-byte type prefix so a
  // resize control message can share the connection with raw keystroke
  // data unambiguously -- see session_daemon.py's _terminal_handler.
  // Registered once, not per-reconnect -- re-registering on every
  // connect() would stack duplicate handlers and send each keystroke
  // multiple times after a few reconnects.
  term.onData((data) => {
    if (ws && ws.readyState === WebSocket.OPEN) ws.send("\x00" + data);
  });

  // xterm.js fires this on any dimension change -- a window resize via
  // setupTerminalFit's fit(), not just user typing -- so this single
  // listener covers every case the terminal's size can change. Without
  // forwarding it, the browser's terminal display resizes but the
  // actual pty (and the CLI running in it) never finds out, so a
  // full-screen program keeps rendering for whatever size it started at.
  //
  // Debounced before it ever reaches the server -- setupTerminalFit
  // retries several times while the page is still settling (fonts,
  // layout, an animation), and each of those can fire onResize with a
  // slightly different size as measurements stabilize. The client-side
  // xterm.js resize itself is cheap and harmless to do repeatedly, but
  // each one that reaches the real pty triggers a SIGWINCH, and a CLI
  // with its own full-screen redraw (Claude Code's own TUI) doing that
  // several times in a tight burst is what produced garbled, overlapping
  // screen contents in practice -- multiple redraws for different
  // assumed widths landing on top of each other. Only sending the
  // settled, final size avoids that redraw storm entirely.
  let resizeSendTimer = null;
  term.onResize(({ cols, rows }) => {
    clearTimeout(resizeSendTimer);
    resizeSendTimer = setTimeout(() => {
      if (ws && ws.readyState === WebSocket.OPEN) ws.send("\x01" + JSON.stringify({ cols, rows }));
    }, 250);
  });

  async function connect() {
    onStatus("connecting…");
    let data;
    try {
      const resp = await fetch(tokenUrl, {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: "csrf_token=" + encodeURIComponent(csrfToken),
      });
      data = await resp.json();
    } catch (e) {
      onStatus("couldn't reach the server — retrying…");
      scheduleReconnect();
      return;
    }
    if (!data.ok) {
      onStatus("couldn't get a terminal token: " + (data.error || "unknown error"));
      return;
    }

    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = proto + "//" + window.location.hostname + ":" + data.port + "/pty/" + sessionId + "?token=" + data.token;
    ws = new WebSocket(wsUrl);
    ws.onopen = () => {
      reconnectAttempt = 0;
      onStatus("connected");
      // A reconnect re-attaches to the same long-running pty, which
      // still thinks it's whatever size it was last told -- possibly
      // stale if the browser window changed size while disconnected
      // (that resize event fired, but had no open socket to send over).
      // Re-declare the current size on every fresh connection so it's
      // never wrong just because of a drop/reconnect.
      ws.send("\x01" + JSON.stringify({ cols: term.cols, rows: term.rows }));
    };
    ws.onmessage = (event) => { term.write(event.data); };
    ws.onclose = (event) => {
      if (manuallyClosed) { onStatus("disconnected"); return; }
      // 4004 = session daemon's own "session not running" close code
      // (session_daemon.py's _terminal_handler) -- retrying against a
      // stopped session forever is pointless noise, so stop and let the
      // caller offer a Start action instead.
      if (event.code === 4004) {
        onStatus("session not running");
        if (onNotRunning) onNotRunning();
        return;
      }
      onStatus("disconnected — reconnecting…");
      scheduleReconnect();
    };
    ws.onerror = () => { /* onclose fires right after; that drives status/reconnect */ };
  }

  function scheduleReconnect() {
    if (manuallyClosed) return;
    reconnectAttempt += 1;
    const delay = Math.min(1000 * Math.pow(2, reconnectAttempt - 1), 15000);
    reconnectTimer = setTimeout(connect, delay);
  }

  function send(data) {
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(data);
  }

  connect();

  return {
    send,
    close() {
      manuallyClosed = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      if (ws) ws.close();
      ws = null;
    },
  };
}

/* Sizes the terminal to fill its container instead of sitting at
   xterm's fixed default (80x24) inside whatever box happens to hold
   it. Only the client-side character grid is resized here -- the real
   pty resize (so a full-screen program like Claude Code itself
   actually uses the extra room) happens via term.onResize, wired up in
   createTerminalConnection above.

   Watches the container with a ResizeObserver rather than a window
   'resize' listener -- a plain window listener only fires for the
   whole browser window changing size, which misses every other way
   the terminal's own box can resize: a CSS drag handle (see
   #terminal-container's `resize: vertical` in session_detail.html), a
   sidebar toggling, any layout shift that isn't the window itself.
   ResizeObserver catches all of those the same way.

   Fitting to the container's exact size is capped at MAX_TERM_COLS/
   MAX_TERM_ROWS -- on a high-res or ultrawide display, a terminal panel
   that fills the whole page can mean several hundred columns, which is
   readable but absurd, and not every CLI's own UI (box-drawing, table
   layouts) handles an arbitrarily wide terminal gracefully. Returns an
   object with a `.fit()` method so call sites don't need to know the
   cap exists -- calling term.resize() directly still fires the same
   onResize event a fit would have, so the capped size still reaches
   the real pty.

   Deliberately NOT using the vendored FitAddon here -- its fit() call
   throws every single time in this build ("Cannot read properties of
   undefined (reading 'scrollBarWidth')"): the vendored xterm.js core
   and xterm-addon-fit.js are a mismatched pair (different file dates,
   and 'scrollBarWidth' doesn't exist anywhere in this xterm.js core at
   all), so the addon crashes trying to read a property its own paired
   core never expected to be missing. Rather than chase down a matching
   vendor pair, computeFitSize() below reimplements the same handful of
   lines FitAddon's own proposeDimensions() does (xterm-addon-fit.js is
   ~30 lines total) using xterm's internal APIs directly, just without
   the one broken property access. */
function computeFitSize(term) {
  if (!term.element || !term.element.parentElement) return null;
  const dims = term._core?._renderService?.dimensions;
  if (!dims || dims.css.cell.width === 0 || dims.css.cell.height === 0) return null;

  const parentStyle = window.getComputedStyle(term.element.parentElement);
  const parentHeight = parseInt(parentStyle.getPropertyValue("height")) || 0;
  const parentWidth = Math.max(0, parseInt(parentStyle.getPropertyValue("width")) || 0);
  const elementStyle = window.getComputedStyle(term.element);
  const availableHeight = parentHeight
    - (parseInt(elementStyle.getPropertyValue("padding-top")) || 0)
    - (parseInt(elementStyle.getPropertyValue("padding-bottom")) || 0);
  const availableWidth = parentWidth
    - (parseInt(elementStyle.getPropertyValue("padding-right")) || 0)
    - (parseInt(elementStyle.getPropertyValue("padding-left")) || 0);

  return {
    cols: Math.max(2, Math.floor(availableWidth / dims.css.cell.width)),
    rows: Math.max(1, Math.floor(availableHeight / dims.css.cell.height)),
  };
}

const MAX_TERM_COLS = 200;
const MAX_TERM_ROWS = 60;

function setupTerminalFit(term) {
  function fit() {
    const size = computeFitSize(term);
    if (!size) return;
    const cols = Math.min(size.cols, MAX_TERM_COLS);
    const rows = Math.min(size.rows, MAX_TERM_ROWS);
    if (cols !== term.cols || rows !== term.rows) term.resize(cols, rows);
  }

  // Character-cell measurement or the container's own layout may not
  // be ready on the very first call (fresh terminal, or right after a
  // display:none -> visible flip) -- there's no event for "now it's
  // ready," so retry across a spread of delays instead of gambling on
  // one. Cheap to over-call -- fit() is a no-op once the size already
  // matches what's there.
  [0, 50, 150, 300, 600, 1000].forEach((delay) => setTimeout(fit, delay));

  // term.element's own parent is the div passed to term.open() -- its
  // size is driven by outer CSS/flex layout, not by xterm itself, so
  // observing it can't create a fit-triggers-resize-triggers-fit loop.
  let resizeTimer = null;
  const observer = new ResizeObserver(() => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(fit, 150);
  });
  observer.observe(term.element.parentElement || term.element);

  return { fit };
}

/* On-screen key row for mobile -- a phone's soft keyboard has no Ctrl/
   Esc/Tab/arrows, and a raw terminal is rough without them. Call once
   per terminal instance; buttons send the real key sequence straight
   over the same connection actual keystrokes use (the server pty
   echoes it back, so there's no separate "write to the terminal"
   step needed here -- that happens the same way it already does for
   typed input). */
function attachMobileKeyRow(container, connection) {
  const keys = [
    { label: "Esc", seq: "\x1b" },
    { label: "Tab", seq: "\t" },
    { label: "Ctrl+C", seq: "\x03" },
    { label: "Ctrl+D", seq: "\x04" },
    { label: "↑", seq: "\x1b[A" },
    { label: "↓", seq: "\x1b[B" },
    { label: "←", seq: "\x1b[D" },
    { label: "→", seq: "\x1b[C" },
  ];
  const row = document.createElement("div");
  row.className = "term-key-row";
  keys.forEach(({ label, seq }) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "term-key-btn";
    btn.textContent = label;
    btn.addEventListener("click", () => connection.send(seq));
    row.appendChild(btn);
  });
  container.appendChild(row);
}

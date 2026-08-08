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
  "catppuccin-mocha": {
    background: "#1e1e2e", foreground: "#cdd6f4", cursor: "#f5e0dc",
    black: "#45475a", red: "#f38ba8", green: "#a6e3a1", yellow: "#f9e2af",
    blue: "#89b4fa", magenta: "#f5c2e7", cyan: "#94e2d5", white: "#bac2de",
    brightBlack: "#585b70", brightRed: "#f38ba8", brightGreen: "#a6e3a1",
    brightYellow: "#f9e2af", brightBlue: "#89b4fa", brightMagenta: "#f5c2e7",
    brightCyan: "#94e2d5", brightWhite: "#a6adc8",
  },
  synthwave: {
    background: "#2a2139", foreground: "#f4eee4", cursor: "#f92aad",
    black: "#34294f", red: "#fe4450", green: "#72f1b8", yellow: "#fede5d",
    blue: "#03edf9", magenta: "#ff7edb", cyan: "#03edf9", white: "#f4eee4",
    brightBlack: "#495495", brightRed: "#fe4450", brightGreen: "#72f1b8",
    brightYellow: "#fede5d", brightBlue: "#03edf9", brightMagenta: "#ff7edb",
    brightCyan: "#03edf9", brightWhite: "#ffffff",
  },
  matrix: {
    background: "#0d0208", foreground: "#00ff41", cursor: "#00ff41",
    black: "#0d0208", red: "#008f11", green: "#00ff41", yellow: "#00b82e",
    blue: "#005f15", magenta: "#00b82e", cyan: "#00cc36", white: "#00ff41",
    brightBlack: "#003b00", brightRed: "#00b82e", brightGreen: "#00ff41",
    brightYellow: "#00ff41", brightBlue: "#00cc36", brightMagenta: "#00ff41",
    brightCyan: "#00ff41", brightWhite: "#ffffff",
  },
  "ayu-dark": {
    background: "#0a0e14", foreground: "#b3b1ad", cursor: "#e6b450",
    black: "#01060e", red: "#ea6c73", green: "#91b362", yellow: "#f9af4f",
    blue: "#53bdfa", magenta: "#fae994", cyan: "#90e1c6", white: "#c7c7c7",
    brightBlack: "#686868", brightRed: "#f07178", brightGreen: "#c2d94c",
    brightYellow: "#ffb454", brightBlue: "#59c2ff", brightMagenta: "#ffee99",
    brightCyan: "#95e6cb", brightWhite: "#ffffff",
  },
  "github-dark": {
    background: "#0d1117", foreground: "#c9d1d9", cursor: "#c9d1d9",
    black: "#484f58", red: "#ff7b72", green: "#3fb950", yellow: "#d29922",
    blue: "#58a6ff", magenta: "#bc8cff", cyan: "#39c5cf", white: "#b1bac4",
    brightBlack: "#6e7681", brightRed: "#ffa198", brightGreen: "#56d364",
    brightYellow: "#e3b341", brightBlue: "#79c0ff", brightMagenta: "#d2a8ff",
    brightCyan: "#56d4dd", brightWhite: "#f0f6fc",
  },
  cyberpunk: {
    background: "#000000", foreground: "#00ff9f", cursor: "#ff2079",
    black: "#000000", red: "#ff2079", green: "#00ff9f", yellow: "#f9f871",
    blue: "#00b7ff", magenta: "#ff2079", cyan: "#00fff9", white: "#d1f7ff",
    brightBlack: "#2d2d2d", brightRed: "#ff5c8a", brightGreen: "#7cffcb",
    brightYellow: "#fff6a3", brightBlue: "#5ccfff", brightMagenta: "#ff5cb3",
    brightCyan: "#7cfff9", brightWhite: "#ffffff",
  },
  // Six original palettes (not reproductions of a specific named
  // community theme -- terminal_theme.py's native-CLI mapping table
  // reflects that by leaving these unmapped/dark-fallback rather than
  // claiming an exact catalog match it can't verify).
  "rose-quartz": {
    background: "#1e1620", foreground: "#f0d9e8", cursor: "#ff8fc7",
    black: "#2b1f2d", red: "#e05780", green: "#7ec9a3", yellow: "#f0c987",
    blue: "#9d8cff", magenta: "#ff8fc7", cyan: "#7ac1d6", white: "#f0d9e8",
    brightBlack: "#5a4a5c", brightRed: "#ff7a9c", brightGreen: "#9de0bd",
    brightYellow: "#ffdca3", brightBlue: "#b9adff", brightMagenta: "#ffb0dc",
    brightCyan: "#9fdbee", brightWhite: "#ffffff",
  },
  "deep-forest": {
    background: "#131a13", foreground: "#cddfc9", cursor: "#8fd694",
    black: "#1e281e", red: "#d9736b", green: "#7fbf6a", yellow: "#d4b96a",
    blue: "#6a9fbf", magenta: "#a482c2", cyan: "#6ac2a3", white: "#cddfc9",
    brightBlack: "#4a5a48", brightRed: "#f28f87", brightGreen: "#9de08a",
    brightYellow: "#ecd48a", brightBlue: "#8bc0e0", brightMagenta: "#c2a0e0",
    brightCyan: "#8ae0c2", brightWhite: "#eaf5e6",
  },
  abyssal: {
    background: "#071019", foreground: "#c5e3f0", cursor: "#4dd8e8",
    black: "#0d1c28", red: "#e0637a", green: "#4dd8a8", yellow: "#e8c15a",
    blue: "#4d9de8", magenta: "#a866d9", cyan: "#4dd8e8", white: "#c5e3f0",
    brightBlack: "#35505f", brightRed: "#ff8296", brightGreen: "#6df0c2",
    brightYellow: "#ffd97a", brightBlue: "#6fb8ff", brightMagenta: "#c085ee",
    brightCyan: "#6ff0ff", brightWhite: "#eaf7fc",
  },
  "sunset-blvd": {
    background: "#1a1023", foreground: "#f5ddc4", cursor: "#ff9d5c",
    black: "#2b1a33", red: "#ff6b6b", green: "#6bcf9e", yellow: "#ffb15c",
    blue: "#7c83ff", magenta: "#d96bff", cyan: "#5cd9d9", white: "#f5ddc4",
    brightBlack: "#5c4266", brightRed: "#ff8f8f", brightGreen: "#8fe0b8",
    brightYellow: "#ffc98f", brightBlue: "#a0a5ff", brightMagenta: "#e79bff",
    brightCyan: "#85e6e6", brightWhite: "#fff0e0",
  },
  "arctic-frost": {
    background: "#0c1620", foreground: "#dceaf2", cursor: "#7fd4f0",
    black: "#16232e", red: "#e2707a", green: "#7fd4a8", yellow: "#e8d07a",
    blue: "#7fb8e8", magenta: "#b07fe8", cyan: "#7fd4f0", white: "#dceaf2",
    brightBlack: "#45596a", brightRed: "#ff9aa2", brightGreen: "#a0f0c8",
    brightYellow: "#ffe8a0", brightBlue: "#a0d4ff", brightMagenta: "#d0a8ff",
    brightCyan: "#a0eeff", brightWhite: "#ffffff",
  },
  "blood-moon-term": {
    background: "#120505", foreground: "#ecc9c9", cursor: "#e0384a",
    black: "#1e0a0a", red: "#e0384a", green: "#7a9e6a", yellow: "#d9a15c",
    blue: "#6a7ea0", magenta: "#a0577a", cyan: "#6a9e9e", white: "#ecc9c9",
    brightBlack: "#5a3232", brightRed: "#ff5c6e", brightGreen: "#9dc48a",
    brightYellow: "#ffc180", brightBlue: "#8ea6cc", brightMagenta: "#cc7ba0",
    brightCyan: "#8ecccc", brightWhite: "#ffe8e8",
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

// Shared between createTerminalConnection and setupTerminalFit (via the
// term instance itself, the one object both already have a reference
// to) -- see markFitReady/_cadrePendingChunks for why write timing
// relative to the first successful fit matters (a one-time thing, at
// connect). This used to also track an in-flight-write counter for
// fit() to defer resizing against, on the theory that resizing mid-
// write was a source of corruption -- removed after confirming the
// terminal's actual corruption source was unrelated (Claude Code's own
// status-line redraw logic, see setupTerminalFit's comment), and after
// finding that counter could get permanently stuck above zero if
// term.write()'s completion callback ever didn't fire for some chunk
// (this vendored xterm.js build already has at least one other known
// bug -- see the FitAddon comment below) -- silently blocking every
// resize from then on until the page was reloaded and a fresh term
// object started the count over. Not worth the risk for a deferral
// that wasn't fixing anything real.
function writeToTerm(term, data) {
  term.write(data);
}

function markFitReady(term) {
  if (term._cadreFitReady) return;
  term._cadreFitReady = true;
  if (term._cadrePendingChunks && term._cadrePendingChunks.length) {
    const combined = term._cadrePendingChunks.join("");
    term._cadrePendingChunks = [];
    writeToTerm(term, combined);
  }
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
      if (manuallyClosed) return;
      onStatus("couldn't reach the server — retrying…");
      scheduleReconnect();
      return;
    }
    // close() (below) can run while the token fetch above was still in
    // flight -- it has no live `ws` to close yet at that point (still
    // null), so without this check the connection this call was told to
    // abandon would open a websocket anyway right here, moments later.
    // That stale connection's onmessage still fires normally, writing
    // its own copy of the backlog into the same shared term instance as
    // whatever connection actually replaced it -- two independent
    // writers landing at slightly different times is exactly what
    // produced interleaved, overlapping-looking corrupted text (not a
    // sizing/resize issue at all, despite how similar the visual
    // symptom looked to that class of bug).
    if (manuallyClosed) return;
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
    ws.onmessage = (event) => {
      // Nothing gets written before the terminal has been sized
      // correctly at least once -- writing the backlog replay (often
      // hundreds of KB, a long session's whole transcript, arriving
      // before setupTerminalFit's settle loop has necessarily run yet)
      // at whatever default size xterm happened to start at corrupts it
      // outright: raw ANSI cursor-positioning bytes captured from a
      // session running at one width don't render correctly at another,
      // and a later resize() can't undo cursor math that already
      // executed wrong. See setupTerminalFit/markFitReady.
      if (!term._cadreFitReady) {
        (term._cadrePendingChunks = term._cadrePendingChunks || []).push(event.data);
        return;
      }
      writeToTerm(term, event.data);
    };
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

   Fits to the container's exact size, uncapped -- returns an object
   with a `.fit()` method so call sites have a stable shape to call
   regardless of what fitting actually involves underneath.

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

// "Large" is NOT a fourth fixed number -- above LARGE_THRESHOLD_COLS
// this returns the container's own real available width, uncapped,
// same continuous-fit behavior the terminal always had (a big/ultrawide
// screen fills completely, the way it did before any of this). Below
// that threshold, snaps down to one of two smaller FIXED tiers instead
// of continuing to shrink continuously. First cut at this capped every
// screen at a flat 180 regardless of how much wider the window actually
// was, which was its own real regression on a big monitor (a large
// swath of unused space where the terminal used to fill the screen) --
// snapping should only ever kick in for screens actually too narrow for
// 180 to fit, never for ones that could comfortably show more.
//
// Two independent reasons the smaller tiers exist at all, not one:
//
// 1. Backlog-replay corruption (see session_daemon.py's
//    MAX_BACKLOG_CHARS comment for the full diagnosis): raw terminal
//    output captured with cursor-positioning math tied to one column
//    width doesn't render correctly replayed at a different one, and
//    fitting continuously on a narrow screen means nearly every
//    distinct device/window/browser-chrome combination lands on its
//    own unique width -- so a reconnect from the *same* physical device
//    essentially never lands on a width any of its own backlog was
//    actually written at. Snapping to a fixed tier means a given device
//    class reliably lands on the same width every time instead.
//
// 2. A genuine Claude Code CLI rendering limitation, confirmed with an
//    isolated synthetic test completely independent of Cadre's own
//    code: its live status/recap area redraws itself with a fixed
//    "cursor up N rows, clear, reprint" sequence that assumes its own
//    content always fits in N rows. When the terminal is narrow enough
//    that a status/recap line wraps onto more rows than N, the redraw
//    only clears the first of those wrapped rows -- the rest are never
//    touched again, and sit in scrollback forever as corrupted-looking
//    leftover fragments. This is upstream CLI behavior Cadre can't fix
//    directly; the only lever available here, once a screen is
//    genuinely too narrow for the uncapped-large path above, is keeping
//    both smaller tiers as wide as practical so *most* status content
//    doesn't wrap. Not a full guarantee even at 180 -- one actually-
//    observed recap line ran 178 characters, right up against it -- so
//    Medium/Small will still hit this sometimes. Deliberate tradeoff
//    (Bradey's call): keep the terminal comfortably narrow on a real
//    small screen rather than force both tiers close enough to 180 to
//    fully dodge an occasional artifact.
const LARGE_THRESHOLD_COLS = 180;
const TERMINAL_COL_TIERS = [150, 120]; // medium / small -- large is uncapped, see above

function snapToColTier(availableCols) {
  // Wide enough for the uncapped "large" path -- fill it completely,
  // same as the terminal always did, instead of snapping down to a
  // fixed number and wasting the rest of a big/ultrawide screen.
  if (availableCols >= LARGE_THRESHOLD_COLS) return availableCols;
  for (const tier of TERMINAL_COL_TIERS) {
    if (tier <= availableCols) return tier;
  }
  // Narrower than even the smallest tier (e.g. a phone in portrait) --
  // use whatever actually fits rather than force an overflowing size.
  return Math.max(2, availableCols);
}

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
    cols: snapToColTier(Math.floor(availableWidth / dims.css.cell.width)),
    rows: Math.max(1, Math.floor(availableHeight / dims.css.cell.height)),
  };
}

function setupTerminalFit(term) {
  function fit() {
    const size = computeFitSize(term);
    if (!size) return false;
    const { cols, rows } = size;
    if (cols !== term.cols || rows !== term.rows) {
      // FitAddon's own (broken) fit() clears the render surface
      // immediately before resizing -- matching that one behavior
      // exactly, just without the property access that actually
      // crashes. Resizes immediately, not deferred against any
      // in-flight write -- see writeToTerm's comment for why a prior
      // version of this deferred and what that cost.
      term._core._renderService.clear();
      term.resize(cols, rows);
    }
    markFitReady(term);
    return true;
  }

  // Character-cell measurement or the container's own layout may not be
  // ready on the very first call (fresh terminal, or right after a
  // display:none -> visible flip) -- there's no event for "now it's
  // ready." Previously this fired fit() at a fixed spread of delays
  // (0/50/150/300/600ms) regardless of whether earlier ones had already
  // succeeded -- if a websocket connection landed its backlog replay in
  // the middle of that window (a real terminal can easily have a lot of
  // freshly-written content by then), *each* later retry that computed
  // even a slightly different size reflowed that same large buffer
  // again, immediately after the last reflow, before it had settled --
  // overlapping, corrupted-looking text, not a clean redraw. Polling
  // instead and stopping at the first successful measurement means
  // exactly one resize happens during startup, not up to six; the
  // ResizeObserver below still catches anything that first measurement
  // got slightly wrong, the same way it catches any later real resize.
  //
  // That alone still wasn't enough on a narrower screen, though: xterm
  // starts at its own default size (80x24) the instant term.open() runs,
  // and createTerminalConnection's connect() (a fetch + websocket open)
  // was firing in parallel with this settle loop, not after it -- on a
  // fast localhost connection the backlog message could arrive and get
  // written to the terminal *before* this loop's first successful
  // measurement ever ran, permanently corrupting that content (ANSI
  // cursor-positioning bytes captured from a session running at one
  // width render incorrectly at a different one, and a later resize()
  // can reflow the buffer but can't undo cursor math that already
  // executed wrong). createTerminalConnection now checks
  // term._cadreFitReady (set by markFitReady below, the first time fit()
  // actually succeeds) and buffers any message that arrives before
  // that, flushing the buffer here in one combined write once sizing is
  // actually correct -- so the very first thing ever written happens at
  // the right size, not just every write after the first stray one.
  let attempts = 0;
  const settleTimer = setInterval(() => {
    attempts += 1;
    if (fit() || attempts >= 20) {
      clearInterval(settleTimer);
      // Layout measurement never succeeded (e.g. the tab was hidden the
      // whole time) -- don't leave incoming content buffered forever
      // waiting for a fit that's never coming; render at whatever
      // default size xterm already has rather than show nothing.
      markFitReady(term);
    }
  }, 50);

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

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
};

function resolveXtermTheme(choice) {
  if (choice === "light") return XTERM_THEMES.light;
  if (choice === "dark") return XTERM_THEMES.dark;
  const prefersLight = window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches;
  return prefersLight ? XTERM_THEMES.light : XTERM_THEMES.dark;
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
  // setupTerminalFit's fitAddon.fit(), not just user typing -- so this
  // single listener covers every case the terminal's size can change.
  // Without forwarding it, the browser's terminal display resizes but
  // the actual pty (and the CLI running in it) never finds out, so a
  // full-screen program keeps rendering for whatever size it started at.
  term.onResize(({ cols, rows }) => {
    if (ws && ws.readyState === WebSocket.OPEN) ws.send("\x01" + JSON.stringify({ cols, rows }));
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
   object with the same `.fit()` shape FitAddon itself has, so call
   sites don't need to know the cap exists -- calling term.resize()
   directly (not through the addon) still fires the same onResize event
   fit() would have, so the capped size still reaches the real pty. */
const MAX_TERM_COLS = 200;
const MAX_TERM_ROWS = 60;

function setupTerminalFit(term) {
  const fitAddon = new FitAddon.FitAddon();
  term.loadAddon(fitAddon);

  function fit() {
    fitAddon.fit();
    const cols = Math.min(term.cols, MAX_TERM_COLS);
    const rows = Math.min(term.rows, MAX_TERM_ROWS);
    if (cols !== term.cols || rows !== term.rows) term.resize(cols, rows);
  }

  // Fitting immediately after the container becomes visible measures it
  // before the browser has actually laid it out (it was display:none a
  // moment ago in the same tick), so it can fit to a 0-size box -- text
  // written after that lands in a terminal with no visible rows until
  // something (a resize, a reload triggering a fresh layout pass) forces
  // a re-fit. Two rAFs reliably land after that layout pass.
  requestAnimationFrame(() => requestAnimationFrame(fit));

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

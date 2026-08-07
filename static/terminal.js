/* Shared interactive-terminal connection logic -- used by both the
   inline toggle on session_detail.html and the dedicated full-page
   terminal view. Handles token fetch, WebSocket connect, and automatic
   reconnect with capped exponential backoff, so a dropped connection
   (mobile network switch, tab backgrounded, a brief daemon restart)
   recovers on its own instead of just sitting there disconnected. */

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
   it -- makes a real difference on the full-page terminal view. Only
   the client-side character grid is resized; the actual pty on the
   server still thinks it's whatever size it was created at (resize
   isn't wired into session_daemon.py's WebSocket protocol yet), so a
   full-screen TUI program (vim, htop) may still render for the old
   size until that's added. Re-fits on window resize/orientation
   change, debounced. */
function setupTerminalFit(term) {
  const fitAddon = new FitAddon.FitAddon();
  term.loadAddon(fitAddon);
  // Fitting immediately after the container becomes visible measures it
  // before the browser has actually laid it out (it was display:none a
  // moment ago in the same tick), so it can fit to a 0-size box -- text
  // written after that lands in a terminal with no visible rows until
  // something (a resize, a reload triggering a fresh layout pass) forces
  // a re-fit. Two rAFs reliably land after that layout pass.
  requestAnimationFrame(() => requestAnimationFrame(() => fitAddon.fit()));

  let resizeTimer = null;
  window.addEventListener("resize", () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => fitAddon.fit(), 150);
  });

  return fitAddon;
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

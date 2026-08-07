// Canvas-based background effects for dashboard themes that a pure CSS
// gradient can't convincingly pull off (proven true for Code Rain --
// a CSS-only approximation didn't read as falling code at all -- and
// again for Rainfall below). Everything else (galaxy, circuit, aurora,
// ...) is static/CSS and doesn't need JS at all.
(function () {
  // Shared by every effect below: a canvas appended as a sibling of
  // <body> (not a descendant) deliberately -- body has its own load-in
  // animation (a transform, even though it settles at translateY(0) and
  // stays there via fill-mode "both"), and any ancestor with a non-none
  // computed transform becomes the containing block for position:fixed
  // descendants. Nested inside body, a canvas would size itself to
  // body's own centered max-width column instead of the real viewport,
  // leaving the sides of the screen blank -- the same bug independently
  // found and fixed for the CSS-only star/particle themes (see
  // style.css's html[data-theme="galaxy"]::before comment). As a
  // sibling of body, a canvas is unaffected by body's CSS either way.
  function makeCanvas(id) {
    const canvas = document.createElement("canvas");
    canvas.id = id;
    canvas.style.position = "fixed";
    canvas.style.inset = "0";
    canvas.style.zIndex = "-1";
    canvas.style.pointerEvents = "none";
    document.documentElement.appendChild(canvas);
    return canvas;
  }

  function startCodeRain() {
    if (document.getElementById("code-rain-canvas")) return null;
    const canvas = makeCanvas("code-rain-canvas");
    const ctx = canvas.getContext("2d");
    const chars = "01";
    const fontSize = 15;
    let columns, drops;

    function resize() {
      canvas.width = window.innerWidth;
      canvas.height = window.innerHeight;
      columns = Math.floor(canvas.width / fontSize);
      drops = new Array(columns).fill(0).map(() => Math.random() * -50);
    }
    resize();
    window.addEventListener("resize", resize);

    function draw() {
      ctx.fillStyle = "rgba(1, 4, 1, 0.08)";
      ctx.fillRect(0, 0, canvas.width, canvas.height);

      ctx.font = fontSize + "px monospace";
      for (let i = 0; i < columns; i++) {
        const char = chars[Math.floor(Math.random() * chars.length)];
        const x = i * fontSize;
        const y = drops[i] * fontSize;

        // Leading character bright, rest of the trail dims via the fade
        // fillRect above (repeated translucent overpaint), not per-glyph
        // opacity -- much cheaper than tracking a trail array per column.
        ctx.fillStyle = "rgba(180, 255, 210, 0.85)";
        ctx.fillText(char, x, y);

        if (y > canvas.height && Math.random() > 0.975) {
          drops[i] = 0;
        }
        drops[i]++;
      }
    }

    const interval = setInterval(draw, 50);
    return { canvas, interval, resize };
  }

  function startRainfall() {
    if (document.getElementById("rainfall-canvas")) return null;
    const canvas = makeCanvas("rainfall-canvas");
    const ctx = canvas.getContext("2d");
    // Slight left-leaning wind on every drop -- a perfectly vertical
    // rain canvas reads as static noise more than weather; the shared
    // diagonal is what actually sells "falling," same reason Code Rain
    // needed real glyphs instead of a gradient.
    const WIND_X = -2.2;
    let drops;

    function makeDrop(canvasHeight) {
      return {
        x: Math.random() * (canvas.width + 200) - 100,
        y: Math.random() * -canvasHeight,
        len: 10 + Math.random() * 18,
        speed: 7 + Math.random() * 9,
        opacity: 0.12 + Math.random() * 0.28,
      };
    }

    function resize() {
      canvas.width = window.innerWidth;
      canvas.height = window.innerHeight;
      // Density scales with area, not a fixed count, so it looks the
      // same "thickness" of rain on a phone-width window as a 4K one.
      const count = Math.floor((canvas.width * canvas.height) / 9000);
      drops = new Array(count).fill(0).map(() => makeDrop(canvas.height));
    }
    resize();
    window.addEventListener("resize", resize);

    function draw() {
      // A hard clear, not Code Rain's translucent-overpaint trail trick
      // -- real rain streaks are crisp, not motion-blurred, so each
      // frame should show clean lines rather than smeared ones.
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.lineCap = "round";
      for (const d of drops) {
        ctx.strokeStyle = `rgba(160, 200, 230, ${d.opacity})`;
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(d.x, d.y);
        ctx.lineTo(d.x + (WIND_X * d.len) / 14, d.y + d.len);
        ctx.stroke();

        d.y += d.speed;
        d.x += (WIND_X * d.speed) / 14;
        if (d.y > canvas.height) {
          d.y = -d.len - Math.random() * 100;
          d.x = Math.random() * (canvas.width + 200) - 100;
        }
      }
    }

    const interval = setInterval(draw, 30);
    return { canvas, interval, resize };
  }

  const EFFECTS = { "code-rain": startCodeRain, "rain": startRainfall };
  let running = null; // { theme, canvas, interval, resize }

  function sync() {
    const theme = document.documentElement.dataset.theme;
    if (running && running.theme !== theme) {
      clearInterval(running.interval);
      window.removeEventListener("resize", running.resize);
      running.canvas.remove();
      running = null;
    }
    if (!running && EFFECTS[theme]) {
      const started = EFFECTS[theme]();
      if (started) running = { theme, ...started };
    }
  }

  function init() {
    sync();
    // Covers any future live data-theme swap (e.g. a settings preview)
    // without needing this script to know about it specifically.
    new MutationObserver(sync).observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["data-theme"],
    });
  }

  // This script is loaded from <head>, before <body> exists yet --
  // the effect starters need document.body, so wait for it on first parse.
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();

// Canvas-based background effects for dashboard themes that a pure CSS
// gradient can't convincingly pull off. Currently just Code Rain --
// everything else (galaxy, circuit, aurora) is static/CSS and doesn't
// need JS at all.
(function () {
  function startCodeRain() {
    if (document.getElementById("code-rain-canvas")) return null;

    const canvas = document.createElement("canvas");
    canvas.id = "code-rain-canvas";
    canvas.style.position = "fixed";
    canvas.style.inset = "0";
    canvas.style.zIndex = "-1";
    canvas.style.pointerEvents = "none";
    document.body.prepend(canvas);

    const ctx = canvas.getContext("2d");
    const chars = "01アイウエオカキクケコサシスセソタチツテト";
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

  let running = null;

  function sync() {
    const isCodeRain = document.documentElement.dataset.theme === "code-rain";
    if (isCodeRain && !running) {
      running = startCodeRain();
    } else if (!isCodeRain && running) {
      clearInterval(running.interval);
      window.removeEventListener("resize", running.resize);
      running.canvas.remove();
      running = null;
    }
  }

  sync();
  // Covers any future live data-theme swap (e.g. a settings preview)
  // without needing this script to know about it specifically.
  new MutationObserver(sync).observe(document.documentElement, {
    attributes: true,
    attributeFilter: ["data-theme"],
  });
})();

// Canvas/DOM-based background effects for dashboard themes that a pure
// CSS gradient can't convincingly pull off (proven true for Code Rain --
// a CSS-only approximation didn't read as falling code at all -- and
// again for Rainfall and Lava Lamp below). Everything else (galaxy,
// circuit, aurora, ...) is static/CSS and doesn't need JS at all.
(function () {
  // Shared by every effect below: appended as a sibling of <body> (not a
  // descendant) deliberately -- body has its own load-in animation (a
  // transform, even though it settles at translateY(0) and stays there
  // via fill-mode "both"), and any ancestor with a non-none computed
  // transform OR filter becomes the containing block for position:fixed
  // descendants. Nested inside body, an effect element would size itself
  // to body's own centered max-width column instead of the real
  // viewport, leaving the sides of the screen blank -- the same bug
  // independently found and fixed for the CSS-only star/particle themes
  // (see style.css's html[data-theme="galaxy"]::before comment). As a
  // sibling of body, an effect element is unaffected by body's CSS
  // either way.
  function attachFixedLayer(el) {
    el.style.position = "fixed";
    el.style.inset = "0";
    el.style.zIndex = "-1";
    el.style.pointerEvents = "none";
    document.documentElement.appendChild(el);
    return el;
  }

  function startCodeRain() {
    if (document.getElementById("code-rain-canvas")) return null;
    const canvas = document.createElement("canvas");
    canvas.id = "code-rain-canvas";
    attachFixedLayer(canvas);
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
    return {
      stop() {
        clearInterval(interval);
        window.removeEventListener("resize", resize);
        canvas.remove();
      },
    };
  }

  function startRainfall() {
    if (document.getElementById("rainfall-canvas")) return null;
    const canvas = document.createElement("canvas");
    canvas.id = "rainfall-canvas";
    attachFixedLayer(canvas);
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
    return {
      stop() {
        clearInterval(interval);
        window.removeEventListener("resize", resize);
        canvas.remove();
      },
    };
  }

  function startLavaLamp() {
    if (document.getElementById("lava-lamp-layer")) return null;
    // No canvas here -- CSS animation instead. The classic "goo" trick:
    // blur the whole group heavily, then crank contrast back up so soft
    // blurred edges snap back to hard ones -- wherever two blobs'
    // blurred halos overlap, contrast pulls that overlap solid too,
    // reading as one blob merging into another instead of two circles
    // overlapping. filter (like transform) creates a containing block
    // for position:fixed descendants -- irrelevant here since nothing
    // inside this layer is itself position:fixed, only position:absolute
    // relative to this already-fixed, already-outside-body wrapper.
    const layer = document.createElement("div");
    layer.id = "lava-lamp-layer";
    attachFixedLayer(layer);
    layer.style.overflow = "hidden";
    layer.style.filter = "blur(28px) contrast(22)";

    const COLORS = ["#fb7185", "#f97316", "#f43f5e", "#fb923c", "#e11d48"];
    const BLOB_COUNT = 8;
    for (let i = 0; i < BLOB_COUNT; i++) {
      const blob = document.createElement("div");
      blob.className = "lava-blob";
      const size = 90 + Math.random() * 150;
      blob.style.width = size + "px";
      blob.style.height = size + "px";
      blob.style.left = Math.random() * 90 + "%";
      blob.style.background = COLORS[i % COLORS.length];
      blob.style.animationDuration = 22 + Math.random() * 16 + "s";
      blob.style.animationDelay = -Math.random() * 30 + "s";
      layer.appendChild(blob);
    }

    return { stop: () => layer.remove() };
  }

  function startDrip() {
    if (document.getElementById("drip-canvas")) return null;
    const canvas = document.createElement("canvas");
    canvas.id = "drip-canvas";
    attachFixedLayer(canvas);
    const ctx = canvas.getContext("2d");
    const LIQUID = "rgba(140, 210, 225, 0.55)";
    const HIGHLIGHT = "rgba(255, 255, 255, 0.35)";
    let runners, poolBumps, t;

    // A pooled mass of liquid sits along the very top edge (poolBumps --
    // overlapping bulges, not a flat band, so it reads as an uneven
    // ledge of liquid rather than a ruled line). From that pool, each
    // runner is a thin trickling strand that slowly lengthens; once it's
    // stretched most of the way to its own (randomized) breaking point,
    // a droplet bulb grows at its tip, then detaches and falls with the
    // same gravity/stretch physics as before -- distinct from a plain
    // falling drop in that there's now a visible strand of liquid
    // connecting it back to the pool the whole time it's trickling.
    function makeRunner(x) {
      return {
        x,
        state: "trickling",
        len: Math.random() * 20,
        maxLen: 50 + Math.random() * 130,
        growRate: 0.15 + Math.random() * 0.35,
        tipR: 0,
        dropY: 0,
        dropVy: 0,
      };
    }

    function poolBaseline(x) {
      // How far the pool's own bulging edge sits below y=0 at this x --
      // runners start from here, not from a flat y=0, so they visibly
      // hang off the pool's uneven underside.
      let h = 6;
      for (const b of poolBumps) {
        const d = Math.abs(x - b.x);
        if (d < 60) h += b.r * 0.4 * Math.max(0, 1 - d / 60);
      }
      return h;
    }

    function resize() {
      canvas.width = window.innerWidth;
      canvas.height = window.innerHeight;
      const spacing = 55;
      const count = Math.max(8, Math.floor(canvas.width / spacing));
      const step = canvas.width / count;
      runners = new Array(count).fill(0).map((_, i) => makeRunner((i + 0.5) * step + (Math.random() * 20 - 10)));
      poolBumps = new Array(count + 4).fill(0).map((_, i) => ({
        x: (i / (count + 3)) * canvas.width,
        r: 10 + Math.random() * 14,
        phase: Math.random() * Math.PI * 2,
      }));
    }
    resize();
    window.addEventListener("resize", resize);
    t = 0;

    function draw() {
      t += 0.02;
      ctx.clearRect(0, 0, canvas.width, canvas.height);

      // The pool: each bump gently pulses in place (a living, not static,
      // mass of liquid), plus a thin connective strip so the bumps read
      // as one pooled ledge instead of separate floating circles.
      ctx.fillStyle = LIQUID;
      for (const b of poolBumps) {
        const r = b.r + Math.sin(t + b.phase) * 1.5;
        ctx.beginPath();
        ctx.ellipse(b.x, 0, r * 1.4, r, 0, 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.fillRect(0, 0, canvas.width, 5);

      for (const r of runners) {
        const baseY = poolBaseline(r.x);
        if (r.state === "trickling") {
          r.len += r.growRate;
          const tipY = baseY + r.len;

          ctx.strokeStyle = LIQUID;
          ctx.lineWidth = 2.2;
          ctx.lineCap = "round";
          ctx.beginPath();
          ctx.moveTo(r.x, baseY);
          ctx.lineTo(r.x, tipY);
          ctx.stroke();

          if (r.len >= r.maxLen * 0.65) {
            r.tipR += 0.05;
            ctx.fillStyle = LIQUID;
            ctx.beginPath();
            ctx.ellipse(r.x, tipY, r.tipR * 0.8, r.tipR, 0, 0, Math.PI * 2);
            ctx.fill();
          }

          if (r.len >= r.maxLen) {
            r.state = "falling";
            r.dropY = tipY;
            r.dropVy = 0.6;
            r.tipR = 0;
            // The runner doesn't fully retract after releasing a drop --
            // a shorter residual strand stays behind and keeps growing
            // from there, same as a real trickle never fully drying up
            // between drops.
            r.len = r.maxLen * 0.35 + Math.random() * (r.maxLen * 0.2);
          }
        } else {
          r.dropVy += 0.35; // gravity
          r.dropY += r.dropVy;
          const stretch = Math.min(1 + r.dropVy * 0.08, 3.2);

          ctx.fillStyle = LIQUID;
          ctx.beginPath();
          ctx.ellipse(r.x, r.dropY, 3, 3 * stretch, 0, 0, Math.PI * 2);
          ctx.fill();
          ctx.fillStyle = HIGHLIGHT;
          ctx.beginPath();
          ctx.ellipse(r.x - 1, r.dropY - stretch, 1, 1.3, 0, 0, Math.PI * 2);
          ctx.fill();

          if (r.dropY - 3 * stretch > canvas.height) {
            r.state = "trickling";
            r.maxLen = 50 + Math.random() * 130;
            r.growRate = 0.15 + Math.random() * 0.35;
          }
        }
      }
    }

    const interval = setInterval(draw, 30);
    return {
      stop() {
        clearInterval(interval);
        window.removeEventListener("resize", resize);
        canvas.remove();
      },
    };
  }

  const EFFECTS = { "code-rain": startCodeRain, "rain": startRainfall, "lava-lamp": startLavaLamp, "drip": startDrip };
  let running = null; // { theme, stop }

  function sync() {
    const theme = document.documentElement.dataset.theme;
    if (running && running.theme !== theme) {
      running.stop();
      running = null;
    }
    if (!running && EFFECTS[theme]) {
      const started = EFFECTS[theme]();
      if (started) running = { theme, stop: started.stop };
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

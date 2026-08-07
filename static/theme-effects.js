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
    const LIQUID = "rgba(120, 200, 220, 0.65)";
    const SHINE = "rgba(220, 250, 255, 0.55)";
    let columns, t;

    // The whole liquid mass -- band plus every icicle -- is built and
    // filled as ONE continuous path per frame, not a wavy band plus
    // separately-filled icicle shapes layered on top of it. Separate
    // opaque fills only ever look seamless where they happen to overlap
    // by exactly the right amount; anywhere they don't (which was most
    // of the width, at the spacing this needs to not look sparse) shows
    // as a visible notch or gap. One continuous outline can't have that
    // problem by construction -- there's only ever one edge.
    function randomMaxLen() {
      // Skewed toward short/medium (pow > 1 biases random() down before
      // scaling), with occasional much longer runs -- most real drips
      // are short, a few run far longer, not a flat/uniform spread.
      return 30 + Math.pow(Math.random(), 1.6) * 280;
    }

    function makeColumn(x) {
      const maxLen = randomMaxLen();
      return {
        x,
        bandY: 12 + Math.random() * 4,
        bandPhase: Math.random() * Math.PI * 2,
        shoulderHalfWidth: 16 + Math.random() * 10,
        // Starts at a random point along its OWN full range, not near
        // zero -- every column beginning its growth in lockstep from
        // "just spawned" was exactly what read as static/synchronized/
        // same-length, since real variation only appeared after each
        // column had independently completed a full grow-and-release
        // cycle, which (at the old slow growRate) took anywhere from 20
        // to 90+ real seconds. Starting pre-scattered across the range
        // means the very first frame already shows a real spread.
        len: Math.random() * maxLen,
        maxLen,
        // Several times faster than before (was 0.12-0.4, ~4-13px/sec)
        // so growth is something you can actually see happening within
        // a few seconds, not an imperceptible creep.
        growRate: 0.6 + Math.random() * 1.4,
        tipR: 5 + Math.random() * 4,
        // A slow side-to-side sway, more pronounced toward the tip than
        // at the band -- the detail that reads as flowing/viscous liquid
        // rather than a rigid, frozen icicle hanging perfectly straight.
        wobblePhase: Math.random() * Math.PI * 2,
        wobbleSpeed: 0.5 + Math.random() * 0.6,
        wobbleAmp: 1.5 + Math.random() * 2.5,
        state: "trickling",
        dropY: 0,
        dropVy: 0,
      };
    }

    function resize() {
      canvas.width = window.innerWidth;
      canvas.height = window.innerHeight;
      const spacing = 95;
      const count = Math.max(6, Math.floor(canvas.width / spacing));
      const step = canvas.width / count;
      columns = new Array(count).fill(0).map((_, i) => makeColumn((i + 0.5) * step + (Math.random() * 24 - 12)));
    }
    resize();
    window.addEventListener("resize", resize);
    t = 0;

    function bandY(c) {
      return c.bandY + Math.sin(t + c.bandPhase) * 1.2;
    }

    function drawSurface() {
      ctx.beginPath();
      ctx.moveTo(-30, -30);
      ctx.lineTo(-30, bandY(columns[0]));

      for (let i = 0; i < columns.length; i++) {
        const c = columns[i];
        const topY = bandY(c);
        const tipY = topY + c.len;
        const neckY = topY + c.len * 0.55;
        const tipR = c.tipR * Math.min(1, c.len / (c.maxLen * 0.4));
        const neckHalfWidth = Math.max(1.5, c.shoulderHalfWidth * 0.3);
        const sw = c.shoulderHalfWidth;
        // Sway grows with distance from the band -- anchored (0) right
        // at the shoulder, most pronounced at the tip -- so it reads as
        // a flexible flowing strand, not a rigid rod pivoting stiffly.
        const wobble = Math.sin(t * c.wobbleSpeed + c.wobblePhase) * c.wobbleAmp;
        const neckX = c.x + wobble * 0.45;
        const tipX = c.x + wobble;

        // Down the icicle's left side, around the bulb, back up the
        // right side -- an icicle silhouette, not a thin stroked line
        // with a separate circle glued to the end of it.
        ctx.lineTo(c.x - sw, topY);
        ctx.quadraticCurveTo(c.x - sw * 0.7, topY + c.len * 0.25, neckX - neckHalfWidth, neckY);
        ctx.quadraticCurveTo(tipX - tipR * 1.1, neckY + (tipY - neckY) * 0.35, tipX - tipR, tipY - tipR * 0.3);
        ctx.quadraticCurveTo(tipX - tipR, tipY + tipR * 0.55, tipX, tipY + tipR * 0.65);
        ctx.quadraticCurveTo(tipX + tipR, tipY + tipR * 0.55, tipX + tipR, tipY - tipR * 0.3);
        ctx.quadraticCurveTo(tipX + tipR * 1.1, neckY + (tipY - neckY) * 0.35, neckX + neckHalfWidth, neckY);
        ctx.quadraticCurveTo(c.x + sw * 0.7, topY + c.len * 0.25, c.x + sw, topY);

        // The shallow "valley" back up to band level before the next
        // icicle -- both endpoints sit at nearly the same y (the band's
        // own small wave), so this reads as a thin continuous strip
        // connecting every icicle, not a gap.
        const next = columns[i + 1];
        if (next) {
          const nextTopY = bandY(next);
          const midX = (c.x + sw + (next.x - next.shoulderHalfWidth)) / 2;
          const midY = (topY + nextTopY) / 2;
          ctx.quadraticCurveTo(c.x + sw, topY, midX, midY);
        } else {
          ctx.lineTo(canvas.width + 30, topY);
        }
      }
      ctx.lineTo(canvas.width + 30, -30);
      ctx.closePath();
      ctx.fillStyle = LIQUID;
      ctx.fill();
    }

    function drawShine(c) {
      const topY = bandY(c);
      const tipY = topY + c.len;
      const neckY = topY + c.len * 0.55;
      const tipR = c.tipR * Math.min(1, c.len / (c.maxLen * 0.4));
      const neckHalfWidth = Math.max(1.5, c.shoulderHalfWidth * 0.3);
      const wobble = Math.sin(t * c.wobbleSpeed + c.wobblePhase) * c.wobbleAmp;
      const neckX = c.x + wobble * 0.45;
      const tipX = c.x + wobble;
      // A thin brighter curve down one side of each icicle reads as a
      // wet highlight -- purely a translucent stroke, so unlike the
      // main fill it's harmless for several to overlap. Follows the same
      // wobble as the fill so it stays glued to the strand's left edge
      // instead of drifting off it as the strand sways.
      ctx.beginPath();
      ctx.moveTo(c.x - c.shoulderHalfWidth * 0.45, topY + c.len * 0.08);
      ctx.quadraticCurveTo(neckX - neckHalfWidth * 0.6, neckY, tipX - tipR * 0.35, tipY - tipR * 0.4);
      ctx.strokeStyle = SHINE;
      ctx.lineWidth = 1.4;
      ctx.lineCap = "round";
      ctx.stroke();
    }

    function draw() {
      t += 0.02;
      ctx.clearRect(0, 0, canvas.width, canvas.height);

      for (const c of columns) {
        if (c.state === "trickling") {
          c.len += c.growRate;
          if (c.len >= c.maxLen) {
            c.state = "falling";
            c.dropY = bandY(c) + c.len;
            c.dropVy = 0.6;
            // The icicle doesn't fully retract after releasing a drop --
            // a shorter residual drip stays behind and keeps growing,
            // same as a real trickle never fully drying up between
            // drops. Crucially, this residual icicle keeps getting drawn
            // below (drawSurface always uses current c.len regardless of
            // state) -- a previous version only drew the icicle while
            // "trickling," leaving a real gap in the band for the whole
            // time a droplet was falling.
            c.len = c.maxLen * 0.35 + Math.random() * (c.maxLen * 0.2);
          }
        }
      }

      drawSurface();
      for (const c of columns) drawShine(c);

      for (const c of columns) {
        if (c.state !== "falling") continue;
        c.dropVy += 0.35; // gravity
        c.dropY += c.dropVy;
        const stretch = Math.min(1 + c.dropVy * 0.08, 3.2);

        ctx.fillStyle = LIQUID;
        ctx.beginPath();
        ctx.ellipse(c.x, c.dropY, c.tipR * 0.7, c.tipR * 0.7 * stretch, 0, 0, Math.PI * 2);
        ctx.fill();
        ctx.fillStyle = SHINE;
        ctx.beginPath();
        ctx.ellipse(c.x - c.tipR * 0.25, c.dropY - stretch, c.tipR * 0.2, c.tipR * 0.3, 0, 0, Math.PI * 2);
        ctx.fill();

        if (c.dropY - c.tipR * stretch > canvas.height) {
          c.state = "trickling";
          c.maxLen = randomMaxLen();
          c.growRate = 0.6 + Math.random() * 1.4;
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

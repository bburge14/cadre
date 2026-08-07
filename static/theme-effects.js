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

  // Same falling-glyph mechanic, different palette per colorway -- keyed
  // by data-theme so the consolidated picker's "Code Rain" family card
  // can offer more than one look without a second copy of this function.
  const CODE_RAIN_PALETTES = {
    "code-rain": { bright: "180, 255, 210", fade: "1, 4, 1" },
    "code-rain-cyber": { bright: "180, 230, 255", fade: "1, 10, 16" },
    "code-rain-crimson": { bright: "255, 180, 195", fade: "10, 1, 2" },
  };

  function startCodeRain() {
    if (document.getElementById("code-rain-canvas")) return null;
    const canvas = document.createElement("canvas");
    canvas.id = "code-rain-canvas";
    attachFixedLayer(canvas);
    const ctx = canvas.getContext("2d");
    const palette = CODE_RAIN_PALETTES[document.documentElement.dataset.theme] || CODE_RAIN_PALETTES["code-rain"];
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
      ctx.fillStyle = `rgba(${palette.fade}, 0.08)`;
      ctx.fillRect(0, 0, canvas.width, canvas.height);

      ctx.font = fontSize + "px monospace";
      for (let i = 0; i < columns; i++) {
        const char = chars[Math.floor(Math.random() * chars.length)];
        const x = i * fontSize;
        const y = drops[i] * fontSize;

        // Leading character bright, rest of the trail dims via the fade
        // fillRect above (repeated translucent overpaint), not per-glyph
        // opacity -- much cheaper than tracking a trail array per column.
        ctx.fillStyle = `rgba(${palette.bright}, 0.85)`;
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

  const RAIN_PALETTES = {
    rain: "160, 200, 230",
    "rain-violet": "190, 160, 230",
    "rain-acid": "170, 220, 120",
  };

  function startRainfall() {
    if (document.getElementById("rainfall-canvas")) return null;
    const canvas = document.createElement("canvas");
    canvas.id = "rainfall-canvas";
    attachFixedLayer(canvas);
    const ctx = canvas.getContext("2d");
    const dropColor = RAIN_PALETTES[document.documentElement.dataset.theme] || RAIN_PALETTES.rain;
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
        ctx.strokeStyle = `rgba(${dropColor}, ${d.opacity})`;
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

    const LAVA_PALETTES = {
      "lava-lamp": ["#fb7185", "#f97316", "#f43f5e", "#fb923c", "#e11d48"],
      "lava-lamp-cosmic": ["#a78bfa", "#818cf8", "#c4b5fd", "#6366f1", "#8b5cf6"],
      "lava-lamp-toxic": ["#a3e635", "#84cc16", "#bef264", "#65a30d", "#d9f99d"],
    };
    const COLORS = LAVA_PALETTES[document.documentElement.dataset.theme] || LAVA_PALETTES["lava-lamp"];
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

  // A real SVG goo filter (blur, then a feColorMatrix that pushes alpha
  // toward binary opaque/transparent, then blend back) -- ported from
  // Bradey's reference implementation. display:none on the <svg> is
  // fine; filter primitives don't need to render to be referenced by
  // url(#id) from the wrapper div's own CSS filter below.
  function ensureGooFilter() {
    if (document.getElementById("drip-goo-filter")) return;
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("style", "display:none;");
    svg.innerHTML =
      '<defs><filter id="drip-goo-filter">' +
      '<feGaussianBlur in="SourceGraphic" stdDeviation="14" result="blur" />' +
      '<feColorMatrix in="blur" mode="matrix" values="1 0 0 0 0  0 1 0 0 0  0 0 1 0 0  0 0 0 50 -25" result="goo" />' +
      '<feBlend in="SourceGraphic" in2="goo" />' +
      "</filter></defs>";
    document.documentElement.appendChild(svg);
  }

  function startDrip() {
    if (document.getElementById("drip-wrapper")) return null;
    ensureGooFilter();

    const wrapper = document.createElement("div");
    wrapper.id = "drip-wrapper";
    attachFixedLayer(wrapper);
    wrapper.style.filter = "url(#drip-goo-filter)";
    wrapper.style.overflow = "hidden";

    const canvas = document.createElement("canvas");
    wrapper.appendChild(canvas);
    const ctx = canvas.getContext("2d");
    // Three tones per colorway, not one flat fill -- a single solid
    // color is exactly what read as a flat cutout/sticker rather than
    // an actual liquid with depth. LIQUID becomes a real canvas
    // gradient (built in resize(), where canvas dimensions are known)
    // running light-to-dark, so the body of the liquid itself carries
    // tonal variation the way a real viscous fluid catching light does.
    const DRIP_PALETTES = {
      drip: { light: "#9ab866", base: "#6f8f3d", dark: "#3c5220" },
      "drip-venom": { light: "#7a539c", base: "#4b2e5e", dark: "#26152f" },
      "drip-blood": { light: "#7a1f1f", base: "#4a0d0d", dark: "#210505" },
    };
    const dripPalette = DRIP_PALETTES[document.documentElement.dataset.theme] || DRIP_PALETTES.drip;
    let LIQUID;
    function buildLiquidGradient() {
      const g = ctx.createLinearGradient(0, 0, 0, Math.max(canvas.height * 0.6, 200));
      g.addColorStop(0, dripPalette.light);
      g.addColorStop(0.55, dripPalette.base);
      g.addColorStop(1, dripPalette.dark);
      LIQUID = g;
    }
    const RUNNER_COUNT = 8;
    let runners, animT, rafId;

    // A second, unfiltered canvas layered on top of the goo-filtered one
    // for crisp specular highlights -- the goo filter's feColorMatrix
    // pushes alpha toward binary opaque/transparent, so any soft
    // gradient drawn *inside* the filtered wrapper would just get
    // flattened back to a flat fill instead of reading as a highlight.
    // Kept fully separate from the base liquid drawing above (not
    // wired into updateRunner/drawRunner/draw at all beyond one new
    // call at the end of draw()) so the shapes/motion that already
    // read right are untouched.
    const shineCanvas = document.createElement("canvas");
    attachFixedLayer(shineCanvas);
    // Blurred rather than crisp -- sharp-edged strokes read as a flat
    // vector-art decal glued on top of the liquid ("cartoonish," per
    // direct feedback), not an actual reflection. A real specular
    // highlight on a wet/glossy surface is soft-edged; this is what
    // turns a drawn stroke into something that looks like light
    // actually catching the liquid instead of a sticker outline.
    shineCanvas.style.filter = "blur(3px)";
    const shineCtx = shineCanvas.getContext("2d");

    function resizeShine() {
      shineCanvas.width = window.innerWidth;
      shineCanvas.height = window.innerHeight;
    }
    resizeShine();
    window.addEventListener("resize", resizeShine);

    function makeRunner(x) {
      return {
        x,
        width: 15 + Math.random() * 15,
        maxLength: 140 + Math.random() * 240,
        speed: 0.6 + Math.random() * 1.0,
        currentLength: Math.random() * 40,
        state: "stretching", // "stretching" | "snapping"
        dropletActive: false,
        dropY: 0,
        dropSpeed: 0,
        dropRadius: 0,
      };
    }

    function resize() {
      canvas.width = window.innerWidth;
      canvas.height = window.innerHeight;
      buildLiquidGradient();
      const spacing = canvas.width / RUNNER_COUNT;
      runners = new Array(RUNNER_COUNT).fill(0).map((_, i) => {
        const x = i * spacing + Math.random() * (spacing - 30) + 15;
        return makeRunner(x);
      });
    }
    resize();
    window.addEventListener("resize", resize);
    animT = 0;

    // A slow sway plus a faster ripple, layered -- an uneven, alive pool
    // surface rather than a single flat sine wave.
    function waveY(x) {
      const slowSway = Math.sin(animT * 0.012 + x * 0.002) * 30;
      const fastRipple = Math.sin(animT * 0.035 + x * 0.008) * 8;
      return 70 + slowSway + fastRipple;
    }

    function updateRunner(r) {
      const startY = waveY(r.x);
      if (r.state === "stretching") {
        r.currentLength += r.speed;
        if (r.currentLength >= r.maxLength) {
          // Snap: spawn a falling droplet right where the tip was, then
          // the strand itself retracts (not an instant reset) before
          // stretching out again -- the visible recoil after a real
          // drip's mass pulls free, not just a clean disappearance.
          r.state = "snapping";
          r.dropletActive = true;
          r.dropY = startY + r.currentLength;
          r.dropSpeed = r.speed * 1.2;
          r.dropRadius = r.width * 0.45;
        }
      } else {
        r.currentLength -= 6;
        if (r.currentLength <= 30) {
          r.state = "stretching";
          r.maxLength = 140 + Math.random() * 240;
          r.speed = 0.6 + Math.random() * 1.0;
        }
      }

      if (r.dropletActive) {
        r.dropSpeed += 0.22; // gravity
        r.dropY += r.dropSpeed;
        if (r.dropY > canvas.height + 50) r.dropletActive = false;
      }
      return startY;
    }

    function drawRunner(r, startY) {
      ctx.fillStyle = LIQUID;
      ctx.beginPath();
      ctx.moveTo(r.x - r.width / 2, startY);

      const tipY = startY + r.currentLength;
      if (r.state === "stretching") {
        // Narrows as it stretches further from resting width -- the
        // longer/thinner a real strand gets pulled, the more it thins,
        // capped at 45% narrower so it never vanishes to a hairline.
        const activeWidth = r.width * (1 - (r.currentLength / r.maxLength) * 0.45);
        ctx.quadraticCurveTo(r.x - r.width / 3, tipY - activeWidth, r.x - activeWidth / 2, tipY);
        ctx.arc(r.x, tipY, activeWidth / 2, Math.PI, 0, true);
        ctx.quadraticCurveTo(r.x + r.width / 3, tipY - activeWidth, r.x + r.width / 2, startY);
      } else {
        ctx.quadraticCurveTo(r.x, tipY + 15, r.x + r.width / 2, startY);
      }
      ctx.closePath();
      ctx.fill();

      if (r.dropletActive) {
        ctx.beginPath();
        ctx.arc(r.x, r.dropY, r.dropRadius, 0, Math.PI * 2);
        ctx.fill();
      }
    }

    // Reads runners' current state (already advanced by updateRunner in
    // the main draw() loop below) and re-derives startY itself via the
    // same pure waveY(x) rather than threading it through -- keeps this
    // additive, with zero edits to the existing update/draw functions'
    // own bodies.
    function drawShine() {
      shineCtx.clearRect(0, 0, shineCanvas.width, shineCanvas.height);

      // A bright crest highlight riding the pool's own wave -- a wet
      // surface catches light along its high points, not evenly.
      shineCtx.beginPath();
      shineCtx.moveTo(0, waveY(0) - 3);
      for (let x = 0; x <= shineCanvas.width; x += 10) {
        shineCtx.lineTo(x, waveY(x) - 3);
      }
      shineCtx.strokeStyle = "rgba(255, 255, 255, 0.4)";
      shineCtx.lineWidth = 2.5;
      shineCtx.lineCap = "round";
      shineCtx.stroke();

      for (const r of runners) {
        const startY = waveY(r.x);
        const tipY = startY + r.currentLength;

        if (r.state === "stretching" && r.currentLength > 6) {
          const activeWidth = r.width * (1 - (r.currentLength / r.maxLength) * 0.45);
          // A short glint near the neck, not a stripe down the whole
          // strand -- running the highlight/shadow the full length is
          // what read as a flat vector-art decal instead of an actual
          // reflection: real specular highlights on a liquid surface
          // are small and localized, not a uniform racing stripe.
          const glintLen = Math.min(r.currentLength, r.currentLength * 0.35 + 14);
          const glintY = startY + glintLen;
          const midY = startY + glintLen * 0.55;

          // A soft dark shading blob near the neck's right side -- a
          // highlight alone doesn't read against an already-colored
          // base fill, so this shadow is what gives the strand a round,
          // glassy cross-section instead of a flat cutout.
          const sx = r.x + r.width * 0.22;
          shineCtx.beginPath();
          shineCtx.moveTo(sx, startY + 4);
          shineCtx.quadraticCurveTo(r.x + activeWidth * 0.3, midY, r.x + activeWidth * 0.16, glintY);
          const shadowGrad = shineCtx.createLinearGradient(sx, startY, sx, glintY);
          shadowGrad.addColorStop(0, "rgba(20, 30, 20, 0.16)");
          shadowGrad.addColorStop(1, "rgba(20, 30, 20, 0)");
          shineCtx.strokeStyle = shadowGrad;
          shineCtx.lineWidth = Math.max(1.4, r.width * 0.16);
          shineCtx.lineCap = "round";
          shineCtx.stroke();

          // A short bright glint near the neck's left side -- the
          // curved-glass-rod highlight a cylindrical strand of liquid
          // actually shows right where it catches the light, fading out
          // well before the tip rather than running the full length.
          const hx = r.x - r.width * 0.2;
          shineCtx.beginPath();
          shineCtx.moveTo(hx, startY + 4);
          shineCtx.quadraticCurveTo(r.x - activeWidth * 0.28, midY, r.x - activeWidth * 0.14, glintY);
          const grad = shineCtx.createLinearGradient(hx, startY, hx, glintY);
          grad.addColorStop(0, "rgba(255, 255, 255, 0.45)");
          grad.addColorStop(1, "rgba(255, 255, 255, 0)");
          shineCtx.strokeStyle = grad;
          shineCtx.lineWidth = Math.max(1.1, r.width * 0.12);
          shineCtx.lineCap = "round";
          shineCtx.stroke();
        }

        if (r.dropletActive) {
          // A dark crescent along the droplet's lower-right rim gives it
          // the same round-glass shading as the runners above, without
          // which the bright highlight below would again be invisible
          // against the droplet's own white fill.
          shineCtx.beginPath();
          shineCtx.ellipse(
            r.x + r.dropRadius * 0.3,
            r.dropY + r.dropRadius * 0.25,
            r.dropRadius * 0.55,
            r.dropRadius * 0.45,
            0.5,
            0,
            Math.PI * 2
          );
          shineCtx.fillStyle = "rgba(20, 30, 20, 0.14)";
          shineCtx.fill();

          // Classic glossy-sphere highlight: a small bright ellipse
          // offset up and to the left of the droplet's own center.
          shineCtx.beginPath();
          shineCtx.ellipse(
            r.x - r.dropRadius * 0.35,
            r.dropY - r.dropRadius * 0.35,
            r.dropRadius * 0.32,
            r.dropRadius * 0.22,
            -0.6,
            0,
            Math.PI * 2
          );
          shineCtx.fillStyle = "rgba(255, 255, 255, 0.55)";
          shineCtx.fill();
        }
      }
    }

    function draw() {
      animT += 1;
      ctx.clearRect(0, 0, canvas.width, canvas.height);

      ctx.fillStyle = LIQUID;
      ctx.beginPath();
      ctx.moveTo(0, 0);
      for (let x = 0; x <= canvas.width; x += 10) {
        ctx.lineTo(x, waveY(x));
      }
      ctx.lineTo(canvas.width, 0);
      ctx.closePath();
      ctx.fill();

      for (const r of runners) {
        const startY = updateRunner(r);
        drawRunner(r, startY);
      }

      drawShine();
    }

    function loop() {
      draw();
      rafId = requestAnimationFrame(loop);
    }
    rafId = requestAnimationFrame(loop);

    return {
      stop() {
        cancelAnimationFrame(rafId);
        window.removeEventListener("resize", resize);
        window.removeEventListener("resize", resizeShine);
        wrapper.remove();
        shineCanvas.remove();
      },
    };
  }

  const EFFECTS = {
    "code-rain": startCodeRain, "code-rain-cyber": startCodeRain, "code-rain-crimson": startCodeRain,
    "rain": startRainfall, "rain-violet": startRainfall, "rain-acid": startRainfall,
    "lava-lamp": startLavaLamp, "lava-lamp-cosmic": startLavaLamp, "lava-lamp-toxic": startLavaLamp,
    "drip": startDrip, "drip-venom": startDrip, "drip-blood": startDrip,
  };
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

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

    const TRAIL_DURATION = 1.1;

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
        // ~28% of columns are "big blob" runs -- a noticeably larger
        // bulb both while gathering and once it falls, with a trailing
        // thread connecting back to the release point that thins and
        // fades over TRAIL_DURATION before finally "snapping" -- the
        // stretchy string a real thick drip leaves behind when a bigger
        // mass pulls free, distinct from a small drop just plopping off.
        isBig: Math.random() < 0.28,
        // A slow side-to-side sway, more pronounced toward the tip than
        // at the band -- the detail that reads as flowing/viscous liquid
        // rather than a rigid, frozen icicle hanging perfectly straight.
        wobblePhase: Math.random() * Math.PI * 2,
        wobbleSpeed: 0.5 + Math.random() * 0.6,
        wobbleAmp: 1.5 + Math.random() * 2.5,
        state: "trickling",
        dropX: 0,
        dropY: 0,
        dropVy: 0,
        releaseX: 0,
        releaseY: 0,
        trailT: 0,
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

    // Threads a smooth curve through a series of points via the
    // standard "control point = real point, curve vertex = midpoint to
    // the next one" trick -- the current path position must already be
    // AT pts[0] before calling. Used per-column below so a strand's
    // width tapers continuously across N sample points instead of
    // collapsing to one fixed narrow width via a single long curve
    // (which is what made long strands look like two thin parallel
    // lines: the "neck" width was a flat constant no matter how far
    // down it had to stretch).
    function curveThroughPoints(pts) {
      for (let i = 1; i < pts.length - 1; i++) {
        const midX = (pts[i].x + pts[i + 1].x) / 2;
        const midY = (pts[i].y + pts[i + 1].y) / 2;
        ctx.quadraticCurveTo(pts[i].x, pts[i].y, midX, midY);
      }
      const last = pts[pts.length - 1];
      const secondLast = pts[pts.length - 2];
      ctx.quadraticCurveTo(secondLast.x, secondLast.y, last.x, last.y);
    }

    // Samples N points down each side of a strand. Width narrows from
    // the shoulder down to a resting width over a SHORT, roughly fixed
    // pixel distance near the band, then holds at that resting width
    // for however much length remains before the bulb -- a real drip's
    // shape is a brief neck followed by a long, roughly uniform body,
    // not a taper that keeps narrowing toward zero the entire way down.
    // (An earlier version scaled the taper to the strand's full length,
    // which for anything long collapsed into a sharp near-zero-width
    // point well before the bulb -- a wide cone with a disconnected-
    // looking circle stuck on the end, not a runner.) Sway grows with
    // fraction-of-length so it's anchored at the band and freest at
    // the tip.
    function columnGeometry(c, topY) {
      const bigMul = c.isBig ? 1.9 : 1;
      const tipR = c.tipR * bigMul * Math.min(1, c.len / (c.maxLen * 0.4));
      const wobbleBase = Math.sin(t * c.wobbleSpeed + c.wobblePhase) * c.wobbleAmp;
      const bulbLen = Math.min(c.len * 0.3, tipR * 1.2);
      const taperLen = Math.max(0, c.len - bulbLen);
      const restHalfWidth = Math.max(2.5, c.shoulderHalfWidth * 0.4);
      const neckDist = Math.min(taperLen, 26); // fixed distance, not proportional to taperLen

      const N = 5;
      const left = [], right = [];
      for (let i = 0; i <= N; i++) {
        const frac = i / N;
        const y = topY + frac * taperLen;
        const progress = neckDist > 0 ? Math.min(1, (frac * taperLen) / neckDist) : 1;
        const hw = c.shoulderHalfWidth + (restHalfWidth - c.shoulderHalfWidth) * progress;
        const wob = wobbleBase * frac;
        left.push({ x: c.x + wob - hw, y });
        right.push({ x: c.x + wob + hw, y });
      }
      return { left, right, tipR, tipX: c.x + wobbleBase, tipY: topY + c.len, wobbleBase };
    }

    function drawSurface() {
      ctx.beginPath();
      ctx.moveTo(-30, -30);
      ctx.lineTo(-30, bandY(columns[0]));

      for (let i = 0; i < columns.length; i++) {
        const c = columns[i];
        const topY = bandY(c);
        const sw = c.shoulderHalfWidth;
        const { left, right, tipR, tipX, tipY } = columnGeometry(c, topY);

        // Down the left taper, around the bulb, back up the right taper
        // -- one continuous outline, not a fixed-width neck segment.
        ctx.lineTo(left[0].x, left[0].y);
        curveThroughPoints(left);
        const preBulbLeft = left[left.length - 1];
        ctx.quadraticCurveTo(tipX - tipR * 1.1, preBulbLeft.y + (tipY - preBulbLeft.y) * 0.5, tipX - tipR, tipY - tipR * 0.3);
        ctx.quadraticCurveTo(tipX - tipR, tipY + tipR * 0.55, tipX, tipY + tipR * 0.65);
        ctx.quadraticCurveTo(tipX + tipR, tipY + tipR * 0.55, tipX + tipR, tipY - tipR * 0.3);
        const preBulbRight = right[right.length - 1];
        ctx.quadraticCurveTo(tipX + tipR * 1.1, preBulbRight.y + (tipY - preBulbRight.y) * 0.5, preBulbRight.x, preBulbRight.y);
        curveThroughPoints([...right].reverse());

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
      const { left, tipR, tipX, tipY } = columnGeometry(c, topY);
      const mid = left[Math.floor(left.length / 2)];
      // A thin brighter curve down one side of each strand reads as a
      // wet highlight -- purely a translucent stroke, so unlike the
      // main fill it's harmless for several to overlap.
      ctx.beginPath();
      ctx.moveTo(c.x - c.shoulderHalfWidth * 0.45, topY + c.len * 0.06);
      ctx.quadraticCurveTo(mid.x + 1.5, mid.y, tipX - tipR * 0.35, tipY - tipR * 0.4);
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
            const topY = bandY(c);
            const wobbleBase = Math.sin(t * c.wobbleSpeed + c.wobblePhase) * c.wobbleAmp;
            c.state = "falling";
            c.dropX = c.x + wobbleBase;
            c.dropY = topY + c.len;
            c.dropVy = 0.6;
            c.releaseX = c.dropX;
            c.releaseY = topY;
            c.trailT = 0;
            // The strand doesn't fully retract after releasing a drop --
            // a shorter residual drip stays behind and keeps growing,
            // same as a real trickle never fully drying up between
            // drops. Crucially, this residual strand keeps getting drawn
            // below (drawSurface always uses current c.len regardless of
            // state) -- a previous version only drew it while
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
        const bigMul = c.isBig ? 1.8 : 1;
        const r = c.tipR * 0.7 * bigMul;

        if (c.isBig && c.trailT < TRAIL_DURATION) {
          c.trailT += 0.03;
          const fade = c.trailT / TRAIL_DURATION;
          const midX = (c.releaseX + c.dropX) / 2;
          const midY = (c.releaseY + c.dropY) / 2;
          ctx.strokeStyle = `rgba(120, 200, 220, ${(0.5 * (1 - fade)).toFixed(3)})`;
          ctx.lineWidth = Math.max(0.4, 2.2 * (1 - fade));
          ctx.lineCap = "round";
          ctx.beginPath();
          ctx.moveTo(c.releaseX, c.releaseY);
          ctx.quadraticCurveTo(midX, midY, c.dropX, c.dropY - r * stretch);
          ctx.stroke();
        }

        ctx.fillStyle = LIQUID;
        ctx.beginPath();
        ctx.ellipse(c.dropX, c.dropY, r, r * stretch, 0, 0, Math.PI * 2);
        ctx.fill();
        ctx.fillStyle = SHINE;
        ctx.beginPath();
        ctx.ellipse(c.dropX - r * 0.3, c.dropY - stretch, r * 0.25, r * 0.35, 0, 0, Math.PI * 2);
        ctx.fill();

        if (c.dropY - r * stretch > canvas.height) {
          c.state = "trickling";
          c.maxLen = randomMaxLen();
          c.growRate = 0.6 + Math.random() * 1.4;
          c.isBig = Math.random() < 0.28;
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

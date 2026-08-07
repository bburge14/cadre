// Wires up every ".tabs" row on the page with horizontal-wheel-scroll
// support and left/right fade arrows that only show up once the row
// actually overflows in that direction -- generic, so any page that
// wants a scrollable tab bar just adds this script tag, no per-page JS.
(function () {
  const CHEVRON_LEFT = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="15 18 9 12 15 6"/></svg>';
  const CHEVRON_RIGHT = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"/></svg>';
  const SCROLL_STEP = 120;

  function wire(tabs) {
    if (tabs.dataset.tabsWired) return;
    tabs.dataset.tabsWired = "1";

    const wrap = document.createElement("div");
    wrap.className = "tabs-wrap";
    tabs.parentNode.insertBefore(wrap, tabs);
    wrap.appendChild(tabs);

    const left = document.createElement("button");
    left.type = "button";
    left.className = "tabs-arrow tabs-arrow-left";
    left.innerHTML = CHEVRON_LEFT;
    left.setAttribute("aria-label", "Scroll tabs left");
    const right = document.createElement("button");
    right.type = "button";
    right.className = "tabs-arrow tabs-arrow-right";
    right.innerHTML = CHEVRON_RIGHT;
    right.setAttribute("aria-label", "Scroll tabs right");
    wrap.appendChild(left);
    wrap.appendChild(right);

    left.addEventListener("click", () => tabs.scrollBy({ left: -SCROLL_STEP, behavior: "smooth" }));
    right.addEventListener("click", () => tabs.scrollBy({ left: SCROLL_STEP, behavior: "smooth" }));

    tabs.addEventListener("wheel", (e) => {
      if (e.deltaY === 0) return;
      tabs.scrollLeft += e.deltaY;
      e.preventDefault();
    }, { passive: false });

    function sync() {
      const maxScroll = tabs.scrollWidth - tabs.clientWidth;
      left.classList.toggle("visible", tabs.scrollLeft > 2);
      right.classList.toggle("visible", tabs.scrollLeft < maxScroll - 2);
    }
    tabs.addEventListener("scroll", sync);
    window.addEventListener("resize", sync);
    // Tab switches can change a wrapped row's natural width (a longer
    // active label, etc.) without firing scroll/resize on their own.
    new MutationObserver(sync).observe(tabs, { childList: true, subtree: true, attributes: true, attributeFilter: ["class"] });
    sync();
  }

  function init() {
    document.querySelectorAll(".tabs").forEach(wire);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();

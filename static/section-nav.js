// Generic sticky sidebar nav for long single-scroll pages -- any page
// that wraps its content in `.page-main` inside `.page-with-nav`, with a
// `<nav class="section-nav">` alongside it, gets a jump-list built from
// that content's own `h2[id]` headings, with the currently-visible one
// highlighted as you scroll. No per-page JS needed to opt in.
(function () {
  function init() {
    const nav = document.querySelector(".section-nav");
    const main = document.querySelector(".page-main");
    if (!nav || !main) return;

    const headings = Array.from(main.querySelectorAll("h2[id]"));
    // A nav with zero or one link isn't navigation -- don't show an
    // empty/useless sidebar for a page that turned out short.
    if (headings.length < 2) {
      nav.style.display = "none";
      return;
    }

    headings.forEach((h) => {
      const a = document.createElement("a");
      a.href = "#" + h.id;
      a.textContent = h.textContent;
      a.dataset.navTarget = h.id;
      nav.appendChild(a);
    });

    const links = nav.querySelectorAll("a");
    function setActive(id) {
      links.forEach((l) => l.classList.toggle("active", l.dataset.navTarget === id));
    }
    setActive(headings[0].id);

    // 0px top / -70% bottom: the observed band starts at the very top of
    // the viewport (not shrunk inward) -- a negative top margin would
    // exclude a heading that lands exactly at y=0, which is exactly
    // where scrollIntoView() (and jump-scrolling in general: End key,
    // dragging a scrollbar thumb straight to an anchor) puts it, with no
    // intermediate scroll frames for the heading to have "passed
    // through" a shrunk-in zone the way a slow wheel-scroll would.
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) setActive(entry.target.id);
        });
      },
      { rootMargin: "0px 0px -70% 0px" }
    );
    headings.forEach((h) => observer.observe(h));

    // Belt-and-suspenders for the last section specifically: if it's
    // short, its heading may never occupy more than the excluded bottom
    // 70% even at the very bottom of the page, so the observer alone
    // might never fire for it. Scrolling to the bottom always means
    // "looking at the last section," regardless of heading geometry.
    function checkBottom() {
      const atBottom = window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 2;
      if (atBottom) setActive(headings[headings.length - 1].id);
    }
    window.addEventListener("scroll", checkBottom, { passive: true });
    checkBottom();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();

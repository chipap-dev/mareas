document.addEventListener("DOMContentLoaded", () => {
  const header = document.querySelector(".site-header");
  const nav = document.getElementById("site-nav");
  const navToggle = document.getElementById("nav-toggle");
  const navLinks = document.querySelectorAll(".site-nav a");
  const backToTop = document.querySelector(".back-to-top");

  // Hamburger toggle
  if (navToggle && nav) {
    navToggle.addEventListener("click", () => {
      const open = nav.classList.toggle("is-open");
      navToggle.classList.toggle("is-open", open);
      navToggle.setAttribute("aria-expanded", open);
    });

    // Cerrar al hacer click en un link
    navLinks.forEach((link) => {
      link.addEventListener("click", () => {
        nav.classList.remove("is-open");
        navToggle.classList.remove("is-open");
        navToggle.setAttribute("aria-expanded", "false");
      });
    });

    // Cerrar al hacer click fuera
    document.addEventListener("click", (e) => {
      if (!header.contains(e.target)) {
        nav.classList.remove("is-open");
        navToggle.classList.remove("is-open");
        navToggle.setAttribute("aria-expanded", "false");
      }
    });
  }

  if (!header) return;

  // Header shadow + back-to-top visibility on scroll
  const updateHeader = () => {
    header.classList.toggle("is-scrolled", window.scrollY > 8);
    if (backToTop) {
      backToTop.classList.toggle("is-visible", window.scrollY > 8);
    }
  };

  updateHeader();
  window.addEventListener("scroll", updateHeader, { passive: true });

  // Non-home pages: mark active by matching full pathname
  if (window.location.pathname !== "/") {
    navLinks.forEach((link) => {
      const href = link.getAttribute("href");
      if (!href || href.includes("#")) return;
      if (
        window.location.pathname === href ||
        (href !== "/" && window.location.pathname.startsWith(href))
      ) {
        link.classList.add("is-active");
      }
    });
    return;
  }

  // Home page: section-based active nav via scroll position
  const sections = document.querySelectorAll("main section[id]");
  const inicioLink = document.querySelector('.site-nav a[href="/"]');

  // Build id → nav link map from anchor hrefs like /#sistemas
  const anchorMap = {};
  navLinks.forEach((link) => {
    const href = link.getAttribute("href");
    if (href && href.startsWith("/#")) {
      anchorMap[href.slice(2)] = link;
    }
  });

  const updateSectionNav = () => {
    const threshold = header.offsetHeight + 40;
    let activeId = null;

    sections.forEach((section) => {
      if (section.offsetTop <= window.scrollY + threshold) {
        activeId = section.id;
      }
    });

    navLinks.forEach((l) => l.classList.remove("is-active"));

    if (activeId && anchorMap[activeId]) {
      anchorMap[activeId].classList.add("is-active");
    } else {
      inicioLink?.classList.add("is-active");
    }
  };

  updateSectionNav();
  window.addEventListener("scroll", updateSectionNav, { passive: true });
});

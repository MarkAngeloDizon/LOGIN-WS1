(() => {
    const sidebar = document.getElementById("sidebar");
    const toggle = document.getElementById("menu-toggle");
    const backdrop = document.getElementById("backdrop");
    const links = document.querySelectorAll(".nav-link[href^='#']");

    function closeSidebar() {
        sidebar.classList.remove("open");
        backdrop.classList.remove("visible");
        toggle.setAttribute("aria-expanded", "false");
    }

    toggle.addEventListener("click", () => {
        const isOpen = sidebar.classList.toggle("open");
        backdrop.classList.toggle("visible", isOpen);
        toggle.setAttribute("aria-expanded", String(isOpen));
    });

    backdrop.addEventListener("click", closeSidebar);

    links.forEach(link => {
        link.addEventListener("click", () => {
            links.forEach(item => item.classList.remove("active"));
            link.classList.add("active");
            closeSidebar();
        });
    });

    window.addEventListener("resize", () => {
        if (window.innerWidth > 900) {
            closeSidebar();
        }
    });
})();
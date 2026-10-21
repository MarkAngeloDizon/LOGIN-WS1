document.addEventListener("DOMContentLoaded", () => {
    const sidebar = document.getElementById("sidebar");
    const toggle = document.getElementById("menu-toggle");
    const backdrop = document.getElementById("backdrop");
    const navLinks = document.querySelectorAll(".nav .nav-link");

    /* ---------- Mobile sidebar ---------- */
    function setMenu(open) {
        sidebar.classList.toggle("open", open);
        backdrop.classList.toggle("show", open);
        toggle.setAttribute("aria-expanded", String(open));
    }

    toggle.addEventListener("click", () => {
        setMenu(!sidebar.classList.contains("open"));
    });

    backdrop.addEventListener("click", () => setMenu(false));

    navLinks.forEach((link) => {
        link.addEventListener("click", () => setMenu(false));
    });

    document.addEventListener("keydown", (e) => {
        if (e.key === "Escape") setMenu(false);
    });

    /* ---------- Highlight nav link of the section in view ---------- */
    const sections = [...navLinks]
        .map((link) => document.querySelector(link.getAttribute("href")))
        .filter(Boolean);

    function setActive(id) {
        navLinks.forEach((link) => {
            link.classList.toggle(
                "active",
                link.getAttribute("href") === "#" + id
            );
        });
    }

    if ("IntersectionObserver" in window) {
        const observer = new IntersectionObserver(
            (entries) => {
                entries.forEach((entry) => {
                    if (entry.isIntersecting) setActive(entry.target.id);
                });
            },
            { rootMargin: "-30% 0px -60% 0px" }
        );

        sections.forEach((section) => observer.observe(section));
    }

    /* ---------- Attendance status colours ---------- */
    const statusSelects = document.querySelectorAll(".status-select");

    function paintStatus(select) {
        select.dataset.status = select.value;
    }

    statusSelects.forEach((select) => {
        paintStatus(select);
        select.addEventListener("change", () => paintStatus(select));
    });

    const markAll = document.getElementById("mark-all-present");

    if (markAll) {
        markAll.addEventListener("click", () => {
            statusSelects.forEach((select) => {
                select.value = "Present";
                paintStatus(select);
            });
        });
    }

    /* ---------- Delete confirmation ---------- */
    document.querySelectorAll("form[data-confirm]").forEach((form) => {
        form.addEventListener("submit", (e) => {
            if (!window.confirm(form.dataset.confirm)) {
                e.preventDefault();
            }
        });
    });

    /* ---------- Prevent double submits ---------- */
    document.querySelectorAll("form").forEach((form) => {
        form.addEventListener("submit", (e) => {
            if (e.defaultPrevented) return;

            form.querySelectorAll('button[type="submit"]').forEach((btn) => {
                // Delay so the form data is still sent.
                setTimeout(() => { btn.disabled = true; }, 0);
            });
        });
    });
});
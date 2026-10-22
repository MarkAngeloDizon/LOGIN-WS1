document.addEventListener("DOMContentLoaded", () => {
    const sidebar = document.getElementById("sidebar");
    const toggle = document.getElementById("menu-toggle");
    const backdrop = document.getElementById("backdrop");
    const navLinks = document.querySelectorAll(".nav .nav-link");
    const MAX_UPLOAD_BYTES = 20 * 1024 * 1024;

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

    /* ---------- File size check (matches the 20 MB server limit) ---------- */
    document.querySelectorAll('input[type="file"]').forEach((input) => {
        input.addEventListener("change", () => {
            const file = input.files && input.files[0];

            if (file && file.size > MAX_UPLOAD_BYTES) {
                window.alert("That file is larger than 20 MB. Choose a smaller file.");
                input.value = "";
            }
        });
    });

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

    /* Re-enable buttons when the page is restored via the back button. */
    window.addEventListener("pageshow", (e) => {
        if (e.persisted) {
            document
                .querySelectorAll('button[type="submit"]')
                .forEach((btn) => { btn.disabled = false; });
        }
    });
});
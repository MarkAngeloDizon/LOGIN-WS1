document.addEventListener("DOMContentLoaded", () => {
    const navLinks = document.querySelectorAll(
        '#nav-bar a[href^="#"]'
    );

    // Highlight the current sidebar section.
    function updateActiveLink() {
        const currentHash = window.location.hash || "#overview";

        navLinks.forEach((link) => {
            link.classList.toggle(
                "active",
                link.getAttribute("href") === currentHash
            );
        });
    }

    navLinks.forEach((link) => {
        link.addEventListener("click", () => {
            navLinks.forEach((item) => item.classList.remove("active"));
            link.classList.add("active");
        });
    });

    window.addEventListener("hashchange", updateActiveLink);
    updateActiveLink();

    // Confirm before disabling or enabling an account.
    document.querySelectorAll(".toggle-account-form").forEach((form) => {
        form.addEventListener("submit", (event) => {
            const disabling = form.dataset.action === "disable";

            const message = disabling
                ? "Disable this account? The user will be signed out and " +
                  "cannot log in until you enable it again."
                : "Enable this account? The user will be able to log in again.";

            if (!window.confirm(message)) {
                event.preventDefault();
            }
        });
    });

    // Confirm before changing the active school year.
    document.querySelectorAll(".activate-year-form").forEach((form) => {
        form.addEventListener("submit", (event) => {
            const confirmed = window.confirm(
                "Activate this school year? The currently active year " +
                "will become inactive."
            );

            if (!confirmed) {
                event.preventDefault();
            }
        });
    });

    // Confirm before starting a database backup download.
    const backupForm = document.getElementById("backup-form");

    if (backupForm) {
        backupForm.addEventListener("submit", (event) => {
            const confirmed = window.confirm(
                "Create and download a SQL database backup?"
            );

            if (!confirmed) {
                event.preventDefault();
            }
        });
    }

    // Require explicit confirmation before submitting a restore.
    const restoreForm = document.getElementById("restore-form");

    if (restoreForm) {
        restoreForm.addEventListener("submit", (event) => {
            const confirmationInput = document.getElementById(
                "confirm-restore"
            );
            const fileInput = document.getElementById("backup-file");

            if (!fileInput.files.length) {
                event.preventDefault();
                window.alert("Please choose a SQL backup file.");
                return;
            }

            if (confirmationInput.value.trim() !== "YES") {
                event.preventDefault();
                window.alert('Type exactly "YES" to confirm the restore.');
                confirmationInput.focus();
                return;
            }

            const confirmed = window.confirm(
                "WARNING: Restoring a database can overwrite existing data. " +
                "Only continue if you have selected a trusted SQL backup " +
                "and understand the consequences. Continue?"
            );

            if (!confirmed) {
                event.preventDefault();
            }
        });
    }

    // Prevent choosing a school-year end date before its start date.
    const startInput = document.getElementById("start-date");
    const endInput = document.getElementById("end-date");

    if (startInput && endInput) {
        startInput.addEventListener("change", () => {
            endInput.min = startInput.value;

            if (endInput.value && endInput.value <= startInput.value) {
                endInput.value = "";
            }
        });
    }
});
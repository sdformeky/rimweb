(() => {
    const checksFor = (scope) =>
        Array.from(document.querySelectorAll(`.bulk-check[data-bulk-scope="${scope}"]`));

    const isVisible = (element) => {
        const row = element.closest("tr, li, label, .bulk-row") || element;
        return !row.hidden && row.offsetParent !== null;
    };

    const selectedIds = (scope) =>
        checksFor(scope).filter((check) => check.checked).map((check) => check.value);

    const refresh = (scope) => {
        const checks = checksFor(scope);
        const selected = checks.filter((check) => check.checked);
        document.querySelectorAll(`.bulk-bar[data-bulk-scope="${scope}"]`).forEach((bar) => {
            bar.querySelectorAll("[data-bulk-count]").forEach((node) => {
                node.textContent = String(selected.length);
            });
            bar.querySelectorAll("[data-bulk-submit]").forEach((button) => {
                button.disabled = selected.length === 0;
            });
            bar.classList.toggle("has-selection", selected.length > 0);
        });
        document.querySelectorAll(`[data-bulk-counter="${scope}"]`).forEach((node) => {
            node.textContent = String(selected.length);
        });
        document.querySelectorAll(`[data-bulk-submit-for="${scope}"]`).forEach((button) => {
            button.disabled = selected.length === 0;
        });
        document.querySelectorAll(`.bulk-check-all[data-bulk-scope="${scope}"]`).forEach((toggle) => {
            const visible = checks.filter(isVisible);
            const visibleSelected = visible.filter((check) => check.checked);
            toggle.checked = visible.length > 0 && visibleSelected.length === visible.length;
            toggle.indeterminate = visibleSelected.length > 0 && visibleSelected.length < visible.length;
        });
    };

    const scopes = new Set(
        Array.from(document.querySelectorAll("[data-bulk-scope], [data-bulk-counter], [data-bulk-submit-for]")).map(
            (node) => node.dataset.bulkScope || node.dataset.bulkCounter || node.dataset.bulkSubmitFor
        )
    );

    document.addEventListener("change", (event) => {
        const target = event.target;
        if (!(target instanceof HTMLInputElement)) {
            return;
        }
        const scope = target.dataset.bulkScope;
        if (!scope) {
            return;
        }
        if (target.classList.contains("bulk-check-all")) {
            checksFor(scope)
                .filter(isVisible)
                .forEach((check) => {
                    check.checked = target.checked;
                });
        }
        refresh(scope);
    });

    document.querySelectorAll(".bulk-bar").forEach((bar) => {
        const scope = bar.dataset.bulkScope;

        bar.querySelectorAll("[data-bulk-clear]").forEach((button) => {
            button.addEventListener("click", () => {
                checksFor(scope).forEach((check) => {
                    check.checked = false;
                });
                refresh(scope);
            });
        });

        bar.querySelectorAll("form[data-bulk-form]").forEach((form) => {
            form.addEventListener("submit", (event) => {
                const ids = selectedIds(scope);
                form.querySelectorAll("input[data-bulk-id]").forEach((input) => input.remove());
                if (ids.length === 0) {
                    event.preventDefault();
                    const hint = bar.querySelector("[data-bulk-hint]");
                    if (hint) {
                        hint.textContent = "Сначала отметьте хотя бы один экземпляр.";
                    }
                    return;
                }
                ids.forEach((id) => {
                    const input = document.createElement("input");
                    input.type = "hidden";
                    input.name = "instance_ids";
                    input.value = id;
                    input.dataset.bulkId = "1";
                    form.appendChild(input);
                });
            });
        });
    });

    document.querySelectorAll("input[data-bulk-filter]").forEach((input) => {
        const scope = input.dataset.bulkFilter;
        input.addEventListener("input", () => {
            const needle = input.value.trim().toLowerCase();
            document.querySelectorAll(`[data-bulk-text][data-bulk-scope="${scope}"]`).forEach((row) => {
                row.hidden = needle !== "" && !row.dataset.bulkText.toLowerCase().includes(needle);
            });
            refresh(scope);
        });
    });

    scopes.forEach(refresh);
})();

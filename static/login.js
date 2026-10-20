(() => {
    const form = document.querySelector(".login-form");
    if (!(form instanceof HTMLFormElement)) {
        return;
    }

    const tokenInput = form.querySelector('input[name="csrf_token"]');
    const refreshUrl = form.dataset.csrfRefreshUrl;
    if (!(tokenInput instanceof HTMLInputElement) || !refreshUrl) {
        return;
    }

    let refreshInProgress = false;

    form.addEventListener("submit", async (event) => {
        if (form.dataset.csrfReady === "true") {
            delete form.dataset.csrfReady;
            return;
        }
        event.preventDefault();
        if (refreshInProgress) {
            return;
        }

        refreshInProgress = true;
        const submitter = event.submitter instanceof HTMLButtonElement ? event.submitter : undefined;
        if (submitter) {
            submitter.disabled = true;
        }

        try {
            const response = await fetch(refreshUrl, {
                method: "GET",
                credentials: "same-origin",
                cache: "no-store",
                headers: { Accept: "application/json" },
            });
            if (!response.ok) {
                throw new Error(`CSRF refresh failed with status ${response.status}`);
            }
            const payload = await response.json();
            if (!payload || typeof payload.csrf_token !== "string" || !payload.csrf_token) {
                throw new Error("CSRF refresh returned an invalid payload");
            }
            tokenInput.value = payload.csrf_token;
        } catch (_error) {
            // Keep the native fallback: the server will reject an actually stale
            // token safely and return the normal localized login error.
        } finally {
            refreshInProgress = false;
            form.dataset.csrfReady = "true";
            form.requestSubmit(submitter);
            if (submitter) {
                submitter.disabled = false;
            }
        }
    });
})();

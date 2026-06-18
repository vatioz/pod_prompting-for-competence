(() => {
  const topicsRoot = document.getElementById("topics-list");
  if (!topicsRoot) {
    return;
  }

  const topicsUrl = topicsRoot.dataset.topicsUrl;
  const refreshIntervalSeconds = Number(topicsRoot.dataset.refreshIntervalSeconds || "0");
  let refreshInFlight = false;

  function setFormError(form, message) {
    let errorEl = document.getElementById("submit-form-error");
    if (!message) {
      if (errorEl) {
        errorEl.remove();
      }
      return;
    }
    if (!errorEl) {
      errorEl = document.createElement("p");
      errorEl.id = "submit-form-error";
      errorEl.className = "error form-error";
      errorEl.setAttribute("role", "alert");
      form.parentNode.insertBefore(errorEl, form);
    }
    errorEl.textContent = message;
  }

  function collectOpenTopicIds() {
    return new Set(
      Array.from(topicsRoot.querySelectorAll("details[data-topic-id][open]"), (element) => element.dataset.topicId)
    );
  }

  function restoreOpenTopicIds(openTopicIds) {
    for (const element of topicsRoot.querySelectorAll("details[data-topic-id]")) {
      element.open = openTopicIds.has(element.dataset.topicId);
    }
  }

  async function refreshTopics() {
    if (!topicsUrl || refreshInFlight) {
      return;
    }
    refreshInFlight = true;
    try {
      const response = await fetch(topicsUrl, {
        headers: {
          "X-Requested-With": "XMLHttpRequest",
          "Cache-Control": "no-cache",
        },
      });
      if (!response.ok) {
        throw new Error(`Failed to refresh topics: ${response.status}`);
      }
      const openTopicIds = collectOpenTopicIds();
      topicsRoot.innerHTML = await response.text();
      restoreOpenTopicIds(openTopicIds);
    } catch (error) {
      console.warn(error);
    } finally {
      refreshInFlight = false;
    }
  }

  async function submitAsyncForm(form) {
    setFormError(form, null);
    const response = await fetch(form.action, {
      method: (form.method || "POST").toUpperCase(),
      body: new FormData(form),
      headers: {
        "X-Requested-With": "XMLHttpRequest",
      },
    });
    if (!response.ok) {
      if (response.status === 422) {
        let payload = null;
        try {
          payload = await response.json();
        } catch (error) {
          payload = null;
        }
        const message = payload && typeof payload.error === "string" ? payload.error : "Please fix the form and try again.";
        setFormError(form, message);
        return;
      }
      throw new Error(`Request failed: ${response.status}`);
    }
    if (form.dataset.resetOnSuccess === "true") {
      form.reset();
    }
    setFormError(form, null);
    await refreshTopics();
  }

  document.addEventListener("submit", (event) => {
    const form = event.target;
    if (!(form instanceof HTMLFormElement)) {
      return;
    }
    if (form.dataset.async !== "true") {
      return;
    }
    event.preventDefault();
    submitAsyncForm(form).catch((error) => {
      console.warn(error);
      window.location.reload();
    });
  });

  if (refreshIntervalSeconds > 0) {
    window.setInterval(refreshTopics, refreshIntervalSeconds * 1000);
  }
})();

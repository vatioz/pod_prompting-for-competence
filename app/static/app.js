(() => {
  const topicsRoot = document.getElementById("topics-list");
  if (!topicsRoot) {
    return;
  }

  const topicsUrl = topicsRoot.dataset.topicsUrl;
  const refreshIntervalSeconds = Number(topicsRoot.dataset.refreshIntervalSeconds || "0");
  let refreshInFlight = false;

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
    const response = await fetch(form.action, {
      method: (form.method || "POST").toUpperCase(),
      body: new FormData(form),
      headers: {
        "X-Requested-With": "XMLHttpRequest",
      },
    });
    if (!response.ok) {
      throw new Error(`Request failed: ${response.status}`);
    }
    if (form.dataset.resetOnSuccess === "true") {
      form.reset();
    }
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

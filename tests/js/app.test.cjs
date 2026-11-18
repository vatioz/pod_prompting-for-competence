const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { JSDOM } = require("jsdom");

const sourcePath = path.resolve(__dirname, "../../app/static/app.js");
const source = fs.readFileSync(sourcePath, "utf8");
const tick = () => new Promise(setImmediate);
const ok = (html = "") => ({ ok: true, text: async () => html });

function setup(t, { root = true, url = "/ui/topics", interval = "5", fetch } = {}) {
  const dom = new JSDOM(`<section>
    <form action="/submit" method="post" data-async="true" data-reset-on-success="true">
      <input name="prompt" value="original">
    </form>
    ${root ? `<div id="topics-list" data-topics-url="${url}" data-refresh-interval-seconds="${interval}">
      <details data-topic-id="a" open></details><details data-topic-id="b"></details>
    </div>` : ""}
  </section>`, { url: "https://example.com" });
  t.after(() => dom.window.close());
  const calls = [], warnings = [], timers = [];
  let reloads = 0;
  const context = vm.createContext({
    document: dom.window.document,
    HTMLFormElement: dom.window.HTMLFormElement,
    FormData: dom.window.FormData,
    console: { warn: (error) => warnings.push(error.message) },
    window: {
      setInterval: (callback, milliseconds) => timers.push({ callback, milliseconds }),
      location: { reload: () => reloads++ },
    },
    fetch: async (...args) => {
      calls.push(args);
      if (!fetch) throw new Error("Unexpected fetch in test");
      return fetch(...args);
    },
  });
  vm.runInContext(source, context, { filename: sourcePath });
  const form = dom.window.document.querySelector("form");
  return {
    dom, form, calls, warnings, timers,
    get reloads() { return reloads; },
    submit(target = form) {
      const event = new dom.window.Event("submit", { bubbles: true, cancelable: true });
      target.dispatchEvent(event);
      return event.defaultPrevented;
    },
    error() { return dom.window.document.getElementById("submit-form-error"); },
  };
}

test("missing topics root leaves forms alone", (t) => {
  const app = setup(t, { root: false });
  assert.equal(app.submit(), false);
  assert.equal(app.timers.length, 0);
  assert.equal(app.calls.length, 0);
});

test("disabled or absent polling interval does not schedule refresh", (t) => {
  for (const interval of ["0", "", "invalid"]) {
    assert.equal(setup(t, { interval }).timers.length, 0);
  }
});

test("refresh replaces markup and preserves only previously open topics", async (t) => {
  const app = setup(t, { fetch: async () => ok('<details data-topic-id="a"></details><details data-topic-id="b" open></details><details data-topic-id="c" open></details>') });
  assert.equal(app.timers[0].milliseconds, 5000);
  await app.timers[0].callback();
  const details = [...app.dom.window.document.querySelectorAll("details")];
  assert.deepEqual(details.map((element) => [element.dataset.topicId, element.open]), [["a", true], ["b", false], ["c", false]]);
  assert.equal(app.calls[0][0], "/ui/topics");
  assert.equal(app.calls[0][1].headers["Cache-Control"], "no-cache");
  assert.equal(app.calls[0][1].headers["X-Requested-With"], "XMLHttpRequest");
});

test("missing topics URL never fetches", async (t) => {
  const app = setup(t, { url: "" });
  await app.timers[0].callback();
  assert.equal(app.calls.length, 0);
});

test("overlapping refreshes are suppressed and failure permits retry", async (t) => {
  let finish;
  const app = setup(t, { fetch: () => new Promise((resolve) => { finish = resolve; }) });
  const first = app.timers[0].callback();
  await app.timers[0].callback();
  assert.equal(app.calls.length, 1);
  finish({ ok: false, status: 503 });
  await first;
  assert.deepEqual(app.warnings, ["Failed to refresh topics: 503"]);
  const second = app.timers[0].callback();
  finish(ok());
  await second;
  assert.equal(app.calls.length, 2);
  assert.equal(app.reloads, 0);
});

test("refresh transport rejection preserves current topics", async (t) => {
  const app = setup(t, { fetch: async () => { throw new Error("offline"); } });
  await app.timers[0].callback();
  assert.equal(app.dom.window.document.querySelectorAll("details").length, 2);
  assert.deepEqual(app.warnings, ["offline"]);
});

test("non-form and synchronous-form submit events are not intercepted", (t) => {
  const app = setup(t);
  assert.equal(app.submit(app.dom.window.document.querySelector("section")), false);
  app.form.dataset.async = "false";
  assert.equal(app.submit(), false);
  assert.equal(app.calls.length, 0);
});

test("successful submit sends form data, resets input and refreshes topics", async (t) => {
  const app = setup(t, { fetch: async (url) => ok(url.endsWith("/submit") ? "" : "<p>new topic</p>") });
  app.form.querySelector("input").value = "changed";
  assert.equal(app.submit(), true);
  await tick();
  const [url, options] = app.calls[0];
  assert.equal(url, "https://example.com/submit");
  assert.equal(options.method, "POST");
  assert.equal(options.body.get("prompt"), "changed");
  assert.equal(options.headers["X-Requested-With"], "XMLHttpRequest");
  assert.equal(app.form.querySelector("input").value, "original");
  assert.equal(app.dom.window.document.getElementById("topics-list").textContent, "new topic");
  assert.equal(app.error(), null);
});

test("submit honors method and does not reset when not configured", async (t) => {
  const app = setup(t, { fetch: async () => ok() });
  app.form.method = "get";
  app.form.dataset.resetOnSuccess = "false";
  app.form.querySelector("input").value = "keep";
  app.submit();
  await tick();
  assert.equal(app.calls[0][1].method, "GET");
  assert.equal(app.form.querySelector("input").value, "keep");
});

test("absent form method falls back to POST", async (t) => {
  const app = setup(t, { fetch: async () => ok() });
  Object.defineProperty(app.form, "method", { value: "" });
  app.submit();
  await tick();
  assert.equal(app.calls[0][1].method, "POST");
});

test("validation errors are accessible, replaced, and cleared on success", async (t) => {
  let message = "Enter a topic";
  const app = setup(t, { fetch: async () => message ? { ok: false, status: 422, json: async () => ({ error: message }) } : ok() });
  app.submit();
  await tick();
  assert.equal(app.error().textContent, "Enter a topic");
  assert.equal(app.error().getAttribute("role"), "alert");
  assert.equal(app.error().className, "error form-error");
  assert.equal(app.error().nextElementSibling, app.form);
  message = "Select a variant";
  app.submit();
  await tick();
  assert.equal(app.error().textContent, "Select a variant");
  assert.equal(app.dom.window.document.querySelectorAll("#submit-form-error").length, 1);
  message = null;
  app.submit();
  await tick();
  assert.equal(app.error(), null);
  assert.equal(app.reloads, 0);
});

test("existing error is updated when validation response arrives", async (t) => {
  let finish;
  const app = setup(t, { fetch: () => new Promise((resolve) => { finish = resolve; }) });
  app.submit();
  const error = app.dom.window.document.createElement("p");
  error.id = "submit-form-error";
  error.textContent = "older concurrent error";
  app.form.before(error);
  finish({ ok: false, status: 422, json: async () => ({ error: "latest error" }) });
  await tick();
  assert.equal(app.error(), error);
  assert.equal(error.textContent, "latest error");
});

test("malformed or missing validation payload uses the fallback message", async (t) => {
  for (const json of [async () => { throw new SyntaxError("invalid JSON"); }, async () => null, async () => ({ error: 42 }), async () => ({})]) {
    const app = setup(t, { fetch: async () => ({ ok: false, status: 422, json }) });
    app.submit();
    await tick();
    assert.equal(app.error().textContent, "Please fix the form and try again.");
    assert.equal(app.calls.length, 1);
    assert.equal(app.reloads, 0);
  }
});

test("submit HTTP and transport errors warn and fall back to page reload", async (t) => {
  for (const [fetch, message] of [
    [async () => ({ ok: false, status: 500 }), "Request failed: 500"],
    [async () => { throw new Error("offline"); }, "offline"],
  ]) {
    const app = setup(t, { fetch });
    app.submit();
    await tick();
    assert.deepEqual(app.warnings, [message]);
    assert.equal(app.reloads, 1);
  }
});

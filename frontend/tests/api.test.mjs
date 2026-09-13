import assert from "node:assert/strict";
import { after, before, test } from "node:test";
import { createServer } from "node:http";
import { api } from "../src/api.ts";

let base;
let requests = 0;
const server = createServer((req, res) => {
  requests += 1;
  if (req.url === "/drop") return req.socket.destroy();
  const match = req.url.match(/^\/status\/(\d+)$/);
  if (match) {
    res.writeHead(Number(match[1]));
    return res.end("upstream-private-diagnostic");
  }
  if (req.url === "/invalid") {
    res.writeHead(200, { "Content-Type": "application/json" });
    return res.end("not JSON; upstream-private-diagnostic");
  }
  if (req.url === "/slow-body") {
    res.writeHead(200, { "Content-Type": "application/json" });
    res.write('{"ok":');
    return setTimeout(() => res.end("true}"), 160);
  }
  const reply = () => {
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ ok: true, method: req.method }));
  };
  if (req.url === "/slow") return setTimeout(reply, 160);
  reply();
});

before(async () => {
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  base = `http://127.0.0.1:${server.address().port}`;
});
after(async () => {
  server.closeAllConnections();
  await new Promise((resolve) => server.close(resolve));
});

test("returns parsed data and preserves POST without retry", async () => {
  const initial = requests;
  assert.deepEqual(await api(base + "/ok", { method: "POST" }), {
    ok: true,
    method: "POST",
  });
  assert.equal(requests - initial, 1);
});

for (const [status, code] of [
  [404, "NOT_FOUND"],
  [409, "CONFLICT"],
  [503, "UNAVAILABLE"],
]) {
  test(`maps HTTP ${status} without disclosing upstream response`, async () => {
    const initial = requests;
    await assert.rejects(api(base + `/status/${status}`), (error) => {
      assert.equal(error.code, code);
      assert.match(error.message, /[А-Яа-я]/);
      assert.ok(!error.message.includes("upstream-private-diagnostic"));
      return true;
    });
    assert.equal(requests - initial, 1);
  });
}

test("malformed JSON becomes a safe response error", async () => {
  await assert.rejects(
    api(base + "/invalid"),
    (error) =>
      error.code === "INVALID_RESPONSE" &&
      !error.message.includes("upstream-private-diagnostic"),
  );
});

for (const route of ["/slow", "/slow-body"]) {
  test(`deadline aborts ${route} including response-body reads`, async () => {
    await assert.rejects(
      api(base + route, undefined, { timeoutMs: 30 }),
      (error) => error.code === "TIMEOUT",
    );
  });
}

test("caller cancellation stays AbortError", async () => {
  const controller = new AbortController();
  const promise = api(base + "/slow", { signal: controller.signal });
  controller.abort();
  await assert.rejects(promise, (error) => error.name === "AbortError");
});

test("pre-cancelled requests never reach the server", async () => {
  const controller = new AbortController();
  controller.abort();
  const initial = requests;
  await assert.rejects(
    api(base + "/ok", { signal: controller.signal }),
    (error) => error.name === "AbortError",
  );
  assert.equal(requests, initial);
});

test("connection reset has a localised network error", async () => {
  await assert.rejects(
    api(base + "/drop"),
    (error) => error.code === "NETWORK" && /[А-Яа-я]/.test(error.message),
  );
});

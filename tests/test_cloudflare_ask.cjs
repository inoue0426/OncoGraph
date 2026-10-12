const assert = require("node:assert/strict");
const test = require("node:test");

test("best drug questions do not call AI or present sampled drugs as recommendations", async () => {
  const { default: worker } = await import("../cloudflare/oncograph-ask.mjs");
  const request = new Request("https://example.workers.dev/ask", {
    method: "POST", headers: { Origin: "https://inoue0426.github.io" },
    body: JSON.stringify({ question: "What is the best drug for breast cancer?", records: [
      { id: "R1", subject: "Fadrozole", predicate: "indicated_for", object: "Breast Cancer" },
    ] }),
  });
  const env = { AI: { run: () => { throw new Error("AI must not be called"); } },
    RATE_LIMITER: { limit: () => { throw new Error("rate limiter must not be called"); } } };
  const response = await worker.fetch(request, env);
  assert.equal(response.status, 200);
  const result = await response.json();
  assert.equal(result.mode, "evidence_limit");
  assert.equal(result.recordsUsed, 0);
  assert(!result.answer.includes("Fadrozole"));
  assert.match(result.answer, /variant is a difference from a reference DNA sequence/i);
  assert.match(result.answer, /tumor.*inherited/i);
});

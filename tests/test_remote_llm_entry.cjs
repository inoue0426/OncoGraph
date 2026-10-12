const assert = require("node:assert/strict");
const test = require("node:test");
const { hostedQuickTunnelUrl } = require("../web/remote-llm-entry.js");

test("opens only a HTTPS quick-tunnel origin and discards untrusted path/query", () => {
  assert.equal(hostedQuickTunnelUrl("https://safe-123.trycloudflare.com/untrusted?x=1"),
    "https://safe-123.trycloudflare.com/#ask");
  for (const value of ["http://safe.trycloudflare.com", "https://trycloudflare.com",
    "https://safe.trycloudflare.com.evil.example", "https://user:pass@safe.trycloudflare.com",
    "https://safe.trycloudflare.com:8443"]) {
    assert.throws(() => hostedQuickTunnelUrl(value));
  }
});

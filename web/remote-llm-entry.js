// The public Pages site opens the separately hosted app; it never sends evidence cross-origin.
function hostedQuickTunnelUrl(raw) {
  const url = new URL(raw);
  if (url.protocol !== "https:" || url.username || url.password || url.port
      || !/^[a-z0-9-]+\.trycloudflare\.com$/i.test(url.hostname)) {
    throw new Error("Enter a HTTPS *.trycloudflare.com URL provided by the owner.");
  }
  return `${url.origin}/#ask`;
}

const remoteEntry = typeof document === "undefined" ? null : document.querySelector("#remote-llm-entry");
if (remoteEntry) remoteEntry.querySelector("form").addEventListener("submit", (event) => {
  event.preventDefault();
  try {
    const target = hostedQuickTunnelUrl(document.querySelector("#remote-llm-url").value);
    document.querySelector("#remote-llm-error").textContent = "";
    window.open(target, "_blank", "noopener,noreferrer");
  } catch (error) { document.querySelector("#remote-llm-error").textContent = error.message; }
});

if (typeof module !== "undefined") module.exports = { hostedQuickTunnelUrl };

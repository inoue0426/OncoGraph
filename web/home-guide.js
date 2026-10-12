// Opening a section link should also reveal tools inside native details panels.
function revealSection(hash) {
  if (!hash || !hash.startsWith("#")) return;
  const target = document.getElementById(decodeURIComponent(hash.slice(1)));
  if (!target) return;
  if (target.matches("details")) target.open = true;
  for (let parent = target.parentElement; parent; parent = parent.parentElement) {
    if (parent.matches("details")) parent.open = true;
  }
}
document.addEventListener("click", (event) => {
  const link = event.target.closest('a[href^="#"]');
  if (link) revealSection(link.hash);
});
window.addEventListener("hashchange", () => revealSection(location.hash));
revealSection(location.hash);

const APPEARANCES = [
  "/assets/mascot/pixel-1.png",
  "/assets/mascot/pixel-2.png",
  "/assets/mascot/pixel-3.png",
  "/assets/mascot/pixel-4.png",
  "/assets/mascot/pixel-5.png",
  "/assets/mascot/pixel-6.png",
];
const APPEARANCE_KEY = "secretary-mascot-appearance";
const APPEARANCE_INTERVAL = 60000;

export class PlushMascot {
  constructor(host) {
    this.host = host;
    this.ready = false;
    this.paused = false;
    this.reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
    this.motion = { walking: false, heading: 0, gait: 0, speed: 0 };
    this.appearance = -1;
    this.appearanceTimer = 0;
  }
  storedAppearance() {
    try {
      const raw = localStorage.getItem(APPEARANCE_KEY);
      if (raw === null || raw === "") return -1;
      const value = Number(raw);
      return Number.isInteger(value) && value >= 0 && value < APPEARANCES.length ? value : -1;
    } catch (_) { return -1; }
  }
  nextAppearance(current) {
    if (current < 0) return Math.floor(Math.random() * APPEARANCES.length);
    const pick = Math.floor(Math.random() * (APPEARANCES.length - 1));
    return pick >= current ? pick + 1 : pick;
  }
  isVisible() { return !document.hidden && this.host.isConnected && this.host.getClientRects().length > 0; }
  start() {
    if (this.appearanceTimer) return;
    this.selectAppearance(this.nextAppearance(this.storedAppearance()));
    this.appearanceTimer = setInterval(() => { if (this.isVisible()) this.selectAppearance(this.nextAppearance(this.appearance)); }, APPEARANCE_INTERVAL);
  }
  selectAppearance(index) {
    const image = document.createElement("img");
    image.className = "mascot-sprite";
    image.alt = ""; image.setAttribute("aria-hidden", "true");
    image.draggable = false;
    image.style.visibility = "hidden";
    image.addEventListener("load", () => {
      if (this.loading !== image) return;
      this.svg?.remove(); this.host.querySelector(".mascot-fallback")?.remove();
      this.svg = image; this.root = image; this.visual = image; this.loading = null;
      image.style.visibility = ""; this.ready = true; this.pose();
    }, { once: true });
    image.addEventListener("error", () => {
      if (this.loading !== image) return;
      image.remove(); this.loading = null; this.ready = Boolean(this.svg);
      if (!this.svg) this.fallback();
    }, { once: true });
    this.loading?.remove(); this.loading = image; this.appearance = index;
    try { localStorage.setItem(APPEARANCE_KEY, String(index)); } catch (_) {}
    image.src = APPEARANCES[index]; this.host.append(image);
  }
  fallback() { if (!this.host.querySelector(".mascot-fallback")) { const node = document.createElement("span"); node.className = "mascot-fallback"; node.setAttribute("aria-hidden", "true"); this.host.append(node); } }
  setLocomotion({ walking = false, heading = 0, gait = 0, speed = 0 } = {}) { this.motion = { walking, heading, gait, speed }; if (this.ready) this.pose(); }
  pose() {
    const stride = this.motion.walking ? Math.sin(this.motion.gait) : 0;
    this.svg.style.transform = this.motion.walking && !this.reduced ? `translateY(${Math.abs(stride) * -2}px) rotate(${stride * 1.5}deg)` : "";
  }
  render() {}
  setPaused(value) { this.paused = value; if (!value && !this.reduced) this.wake(); }
  setReduced(value) { this.reduced = value; if (value) this.setLocomotion(); this.setPaused(this.paused || value); }
  wake() {}
}

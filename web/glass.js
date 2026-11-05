// The glass lip re-images the engraved field through nested, curved optical bands.
(() => {
  const field = document.getElementById("cloudField");
  if (!field) return;

  const tiles = [...document.querySelectorAll(".bento .metric, .bento .health-panel")].map(tile => {
    const rim = document.createElement("canvas");
    rim.className = "glass-rim";
    rim.setAttribute("aria-hidden", "true");
    tile.prepend(rim);
    return {tile, rim, ctx: rim.getContext("2d")};
  });
  let pending = 0;

  function draw() {
    pending = 0;
    const backdrop = field.getBoundingClientRect();
    if (!backdrop.width || !backdrop.height) return;
    const sx = field.width / backdrop.width, sy = field.height / backdrop.height;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    for (const {tile, rim, ctx} of tiles) {
      const rect = rim.getBoundingClientRect();
      const {width: w, height: h} = rect;
      if (!ctx || !w || !h || rect.bottom <= 0 || rect.top >= window.innerHeight) continue;
      const pw = Math.round(w*dpr), ph = Math.round(h*dpr);
      if (rim.width !== pw || rim.height !== ph) {
        rim.width = pw;
        rim.height = ph;
      }
      ctx.setTransform(pw/w, 0, 0, ph/h, 0, 0);
      ctx.clearRect(0, 0, w, h);
      const radius = Math.min(parseFloat(getComputedStyle(tile).borderTopLeftRadius), w/2, h/2);
      const lip = Math.min(13, radius, w/4, h/4);
      const bands = Math.ceil(lip);
      for (let i = 0; i < bands; i++) {
        const a = i*lip/bands, b = (i+1)*lip/bands;
        const t = (i+.5)/bands;
        // Zero displacement at both boundaries keeps ink continuous into and out of the bevel.
        const displacement = lip * 1.45 * Math.sin(Math.PI*t);
        ctx.save();
        ctx.beginPath();
        ctx.roundRect(a, a, w-2*a, h-2*a, Math.max(0, radius-a));
        ctx.roundRect(b, b, w-2*b, h-2*b, Math.max(0, radius-b));
        ctx.clip("evenodd");
        ctx.globalAlpha = .88 * Math.min(1, (1-t)*4);
        ctx.drawImage(field,
          (rect.left-backdrop.left-displacement)*sx, (rect.top-backdrop.top-displacement)*sy,
          (w+2*displacement)*sx, (h+2*displacement)*sy, 0, 0, w, h);
        ctx.restore();
      }
    }
  }
  function schedule() {
    if (!pending) pending = requestAnimationFrame(draw);
  }
  window.addEventListener("cloud-field-drawn", schedule);
  window.addEventListener("scroll", schedule, {passive: true});
  window.addEventListener("resize", schedule);
  const observer = new ResizeObserver(schedule);
  for (const {tile} of tiles) observer.observe(tile);
  draw();
})();

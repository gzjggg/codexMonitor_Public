// Two plates in the same ink. Both are drawn once at display resolution.
(() => {
  const paper = "#f0e7cc", ink = "#233b77", pale = "#59628a";
  const tau = 2 * Math.PI;

  function noise(seed) {
    return () => {
      seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0;
      return seed / 4294967296;
    };
  }

  function cloud(ctx, x, y, angle, r, length, rng) {
    ctx.save();
    ctx.translate(x, y);
    ctx.rotate(angle);
    const lobes = 9 + Math.floor(rng() * 5), phase = rng() * tau;
    const outline = new Path2D();
    for (let i = 0; i <= lobes * 12; i++) {
      const a = i / (lobes * 12) * tau;
      const ripple = .83 + .19 * Math.abs(Math.sin(lobes * a / 2))
        + .06 * Math.sin(a * 3 + phase) + .03 * Math.sin(a * 5 - phase);
      const px = Math.cos(a) * length * ripple, py = Math.sin(a) * r * ripple;
      if (!i) outline.moveTo(px, py);
      else outline.lineTo(px, py);
    }
    outline.closePath();
    ctx.fillStyle = paper;
    ctx.fill(outline);
    ctx.lineWidth = Math.max(.55, Math.min(1.4, r * .054));
    ctx.strokeStyle = ink;
    ctx.stroke(outline);
    ctx.clip(outline);
    // Oblique burin strokes gather along the lower flank of each swelling.
    ctx.beginPath();
    for (let u = -length; u < length; u += Math.max(1.7, r * .105)) {
      const bowl = Math.sqrt(Math.max(0, 1 - (u / length) ** 2));
      const root = r * (.35 + .09 * Math.sin(phase + u / r)) * bowl;
      ctx.moveTo(u, root);
      ctx.quadraticCurveTo(u + 2, r * .76 * bowl, u + r * .27, r * 1.16);
    }
    ctx.strokeStyle = pale;
    ctx.lineWidth = .63;
    ctx.stroke();
    if (r > 8) {
      // An open echo of the outer arc leaves the lit face unengraved.
      ctx.beginPath();
      ctx.moveTo(length * .07, -r * .72);
      ctx.bezierCurveTo(length * .53, -r * .89, length * .66, -r * .39, length * .61, -r * .25);
      ctx.strokeStyle = ink;
      ctx.lineWidth = .66;
      ctx.stroke();
    }
    ctx.restore();
  }

  function branch(ctx, knots, r0, r1, seed) {
    const rng = noise(seed);
    let lastX, lastY, step = 0, station = 0;
    for (let k = 0; k < knots.length - 1; k++) {
      const p = knots[k], q = knots[k+1], pre = knots[k-1] || p, post = knots[k+2] || q;
      const steps = Math.ceil(Math.hypot(q[0]-p[0], q[1]-p[1]) / 2);
      for (let i = 0; i <= steps; i++) {
        const t = i / steps, s = (k+t) / (knots.length-1);
        const pt = p.map((v,d) => .5 * (2*v + (-pre[d]+q[d])*t +
          (2*pre[d]-5*v+4*q[d]-post[d])*t*t + (-pre[d]+3*v-3*q[d]+post[d])*t*t*t));
        if (lastX !== undefined && Math.hypot(pt[0]-lastX, pt[1]-lastY) < step) continue;
        const angle = lastX === undefined ? Math.atan2(q[1]-p[1],q[0]-p[0]) : Math.atan2(pt[1]-lastY,pt[0]-lastX);
        const r = (r0*(1-s) + r1*s) * (.8 + .3*Math.sin(s*17+seed)**2) * (.92 + .16*rng());
        if (r > 13 && station % 4 === 0) {
          const flank = (station % 8 === 0 ? -1 : 1) * r * .78;
          cloud(ctx,pt[0]-Math.sin(angle)*flank,pt[1]+Math.cos(angle)*flank,
                angle+.3,r*.64,r*(.47+.18*rng()),rng);
        }
        cloud(ctx, pt[0], pt[1], angle, r, r*(.62+.35*rng()), rng);
        station++;
        step = Math.max(3.2, r*(.43+.19*rng()));
        [lastX,lastY] = pt;
      }
    }
  }

  function paperGround(ctx, w, h, header) {
    ctx.fillStyle = paper;
    ctx.fillRect(0, 0, w, h);
    const rng = noise(574);
    ctx.fillStyle = "rgba(84,58,32,.10)";
    for (let i=0; i<w*h/95; i++) ctx.fillRect(rng()*w,rng()*h,.7+rng(),.52);
    if (header) return;
    ctx.strokeStyle = "rgba(42,59,108,.06)";
    ctx.lineWidth = .6;
    ctx.beginPath();
    for (let x=0; x<w; x+=40) {ctx.moveTo(x,0);ctx.lineTo(x,h);}
    for (let y=0; y<h; y+=40) {ctx.moveTo(0,y);ctx.lineTo(w,y);}
    ctx.stroke();
  }

  function register(ctx, x, y, label) {
    ctx.strokeStyle = pale;
    ctx.lineWidth = .7;
    ctx.beginPath(); ctx.moveTo(x,y); ctx.lineTo(x+17,y-21); ctx.lineTo(x+38,y-21); ctx.stroke();
    ctx.fillStyle = ink;
    ctx.font = "9px Consolas, monospace";
    ctx.fillText(label,x+41,y-18);
  }

  function headerPlate(ctx, w, h) {
    const narrow = w < 600;
    const z = Math.min(w/(narrow ? 700 : 1080),h/(narrow ? 350 : 245));
    ctx.translate(w-z*(narrow ? 704 : 748),narrow ? h-z*223 : (h-z*228)/2);
    ctx.scale(z,z);
    function frond(x, y, length, angle, bow, breadth) {
      ctx.save(); ctx.translate(x,y); ctx.rotate(angle);
      ctx.strokeStyle = ink; ctx.fillStyle = paper;
      ctx.beginPath(); ctx.moveTo(0,0); ctx.quadraticCurveTo(length/2,bow*2,length,0);
      ctx.lineWidth = 1.8; ctx.stroke();
      for (let n=0;n<23;n++) {
        for (const side of [-1,1]) {
          const t=.13+(n+(side+1)*.17)*.0375;
          const span=breadth*Math.sin(Math.PI*t)**.76*(1-.45*t);
          ctx.save(); ctx.translate(t*length,4*bow*t*(1-t));
          ctx.rotate(Math.atan2(4*bow*(1-2*t),length)+side*(1.17-.49*t));
          ctx.beginPath(); ctx.moveTo(0,0); ctx.quadraticCurveTo(span*.5,-side*3,span,0);
          ctx.lineWidth=.85; ctx.stroke();
          for(let i=0;i<10;i++) {
            const u=i/10, leaf=span*.24*(1-u*.86);
            for(const s of [-1,1]) {
              const ax=span*(u+.023*(s+1)), ay=-side*6*u*(1-u);
              ctx.beginPath(); ctx.moveTo(ax,ay);
              ctx.quadraticCurveTo(ax+leaf*.08,ay+s*leaf*.8,ax+leaf*.92,ay+s*leaf);
              ctx.quadraticCurveTo(ax+leaf*.72,ay+s*leaf*.27,ax,ay);
              ctx.fill(); ctx.lineWidth=.63; ctx.stroke();
              ctx.beginPath(); ctx.moveTo(ax,ay); ctx.lineTo(ax+leaf*.68,ay+s*leaf*.79);
              ctx.lineWidth=.34; ctx.stroke();
            }
          }
          ctx.restore();
        }
      }
      ctx.restore();
    }
    frond(161,206,240,-.93,-9,47);
    frond(157,209,440,-.09,9,43);
    frond(153,210,519,-.33,-25,83);
    // The young frond ends in a tight circinate coil.
    ctx.beginPath(); ctx.moveTo(151,210); ctx.bezierCurveTo(182,176,166,124,147,111);
    for(let j=0;j<=120;j++){
      const a=-Math.PI/2-j*.092, r=20*(1-j/130);
      ctx.lineTo(147+r*Math.cos(a),131+r*Math.sin(a));
    }
    ctx.strokeStyle=ink; ctx.lineWidth=2.6; ctx.stroke();
    register(ctx,144,119, "CROZIER");
    register(ctx,457,118, "PINNA");
  }

  function fieldPlate(ctx,w,h) {
    const z = Math.max(w/1350,h/900,.68);
    ctx.translate((w-1350*z)/2,(h-900*z)/2);
    ctx.scale(z,z);
    // A fulminating crown on the left crosses the radial manifold on the right.
    const pipes = [
      [[[-60,365],[110,399],[250,349],[335,271],[416,247],[525,283]],10,19],
      [[[195,-65],[264,34],[390,78],[469,183],[611,188],[746,132],[875,24],[1019,-38]],12,17],
      [[[590,-55],[571,76],[629,154],[703,248],[812,275],[932,371]],9,22],
      [[[940,351],[1034,295],[1109,180],[1110,64],[1173,-42]],15,8],
      [[[946,355],[1074,351],[1206,311],[1308,194],[1386,184]],17,8],
      [[[946,353],[1047,388],[1191,410],[1329,390],[1415,321]],13,6],
      [[[909,372],[1008,448],[1120,571],[1199,680],[1280,742],[1404,724]],18,12],
      [[[920,371],[955,492],[1032,603],[1085,711],[1067,824],[1079,958]],10,18],
      [[[929,371],[832,486],[752,579],[629,629],[525,723],[476,865],[395,954]],13,16],
      [[[934,352],[799,369],[670,435],[547,439],[421,358],[267,324],[130,245],[16,252],[-73,193]],18,27],
      [[[-66,612],[52,573],[135,539],[211,437],[273,393],[351,426],[449,501],[579,530],[663,483],[745,438]],24,11],
      [[[941,356],[989,271],[1046,215],[1156,223],[1225,269],[1379,289]],7,14],
      [[[911,372],[874,463],[851,594],[787,697],[664,791],[569,817],[465,778],[365,764],[277,832],[173,942]],8,22],
      [[[-80,19],[67,65],[140,31],[199,-17],[281,-53]],36,23],
      [[[-65,286],[32,218],[84,130],[147,117],[196,157],[253,181],[311,163],[374,79],[458,-36]],25,29],
      [[[1430,806],[1311,771],[1232,837],[1209,923],[1108,947]],42,24]
    ];
    pipes.forEach(([knots,a,b],i)=>branch(ctx,knots,a,b,117+i*19));
    const rng = noise(901);
    branch(ctx,[[-65,164],[28,115],[102,164],[151,249],[222,294],[292,292],[356,326],[422,358]],28,16,179);
    branch(ctx,[[409,-66],[457,18],[505,60],[558,61],[609,84],[656,152],[715,227]],34,19,203);
    branch(ctx,[[-54,698],[31,670],[98,685],[162,754],[217,790],[255,830]],17,9,272);
    for (const [x,y,r] of [[145,235,32],[171,262,43],[194,284,31],[146,271,25],
                             [337,151,26],[358,122,32],[477,33,42],[504,54,33],
                             [220,433,29],[241,408,35],[267,396,25],[545,722,23]])
      cloud(ctx,x,y,rng()*tau,r,r*(.8+.3*rng()),rng);
    for (const [x,y,r] of [[894,339,40],[927,356,48],[953,322,30],[962,379,33],[912,390,30]])
      cloud(ctx,x,y,-.7,r,r*1.18,rng);
  }

  function mount(id, plate) {
    const canvas = document.getElementById(id);
    const ctx = canvas?.getContext("2d");
    if (!ctx) return;
    function draw() {
      const {width:w,height:h} = canvas.getBoundingClientRect();
      if (!w || !h) return;
      const dpr = Math.min(window.devicePixelRatio || 1, 2.5);
      const width = Math.round(w*dpr), height = Math.round(h*dpr);
      if (canvas.width === width && canvas.height === height && canvas.dataset.rendered) return;
      canvas.width=width; canvas.height=height;
      ctx.setTransform(dpr,0,0,dpr,0,0); ctx.lineCap="round"; ctx.lineJoin="round";
      paperGround(ctx,w,h,id==="blueprint");
      plate(ctx,w,h);
      canvas.dataset.rendered="true";
      if (id==="cloudField") window.dispatchEvent(new Event("cloud-field-drawn"));
    }
    draw();
    new ResizeObserver(draw).observe(canvas);
    window.addEventListener("resize",draw);
  }
  mount("cloudField",fieldPlate);
  mount("blueprint",headerPlate);
})();

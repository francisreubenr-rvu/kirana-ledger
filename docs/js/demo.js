/* Demo page controller. In-browser mode uses window.Kirana (kirana-core.js) with state in localStorage;
 * backend mode calls a running FastAPI server's /text, /ledger, /summary, /reminders and /reset. */
(function () {
  "use strict";
  const K = window.Kirana;
  const $ = (id) => document.getElementById(id);
  const STORE = "kirana-ledger-demo-v1";
  const BKEY = "kirana-ledger-backend";
  const BCP47 = { hi: "hi-IN", kn: "kn-IN", ta: "ta-IN", en: "en-IN" };
  const LANG_NAME = { hi: "Hindi", kn: "Kannada", ta: "Tamil", en: "English" };
  const esc = (s) => String(s === null || s === undefined ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const money = (x) => (x === null || x === undefined ? "—" : "₹" + Number(x).toLocaleString("en-IN", { maximumFractionDigits: 2 }));
  const qty = (x) => Number(x).toLocaleString("en-IN", { maximumFractionDigits: 2 });

  // ---------------------------------------------------------------- state
  let ledger = loadLedger();
  let agent = new K.Agent(ledger);
  let backend = null;      // base URL when connected
  let lastReply = null;    // {text, lang, audio_b64}
  let audioEl = null;

  function loadLedger() {
    try {
      const raw = localStorage.getItem(STORE);
      if (raw) return new K.Ledger(JSON.parse(raw));
    } catch (e) { /* corrupted or blocked storage: start fresh */ }
    const L = new K.Ledger();
    L.seedDemo(true);
    return L;
  }
  function save() { try { localStorage.setItem(STORE, JSON.stringify(ledger.toJSON())); } catch (e) { /* private mode */ } }

  // ------------------------------------------------------------- samples
  const FALLBACK_SAMPLES = [
    { id: "hi-01", lang: "hi", text: "Ramesh ka 240 udhaar, 2 Aashirvaad 5kg bik gaye" },
    { id: "kn-02", lang: "kn", text: "Lakshmi 300 kottru" },
    { id: "ta-01", lang: "ta", text: "Murugan ku 200 kadan" },
    { id: "hi-05", lang: "hi", text: "aaj ka hisaab batao" },
  ];
  function renderChips(samples) {
    const tag = { hi: "HI", kn: "KN", ta: "TA", en: "EN" };
    $("chips").innerHTML = samples.map((s, i) =>
      `<button type="button" class="chip" data-i="${i}" title="${esc(s.id)}"><span class="tag">${tag[s.lang] || s.lang}</span>${esc(s.text)}</button>`).join("");
    $("chips").querySelectorAll(".chip").forEach((b) => b.addEventListener("click", () => {
      $("utter").value = samples[+b.dataset.i].text;
      run();
    }));
  }
  fetch("data/utterances.json").then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
    .then(renderChips).catch(() => renderChips(FALLBACK_SAMPLES));

  // ----------------------------------------------------------------- run
  async function run() {
    const text = $("utter").value.trim();
    if (!text) { $("utter").focus(); return; }
    const forced = $("lang").value;
    $("run").disabled = true;
    try {
      let out;
      if (backend) {
        const body = { text, speak: $("speak").value === "1" };
        if (forced !== "auto") body.lang = forced;
        const r = await fetch(backend + "/text", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
        if (!r.ok) throw new Error(`/text returned HTTP ${r.status}`);
        out = await r.json();
      } else {
        out = agent.handleText(text, forced === "auto" ? "" : forced);
        save();
      }
      showResult(out);
      await refresh(out.actions);
      if ($("speak").value === "1") speak();
    } catch (e) {
      setStatus("bad", `Backend call failed: ${e.message}. Switch back to in-browser mode or check the server and its CORS_ORIGINS.`);
    } finally {
      $("run").disabled = false;
    }
  }

  function showResult(out) {
    const provider = out.provider || "";
    $("meta").innerHTML = `Heard: <b>${esc(out.transcript)}</b> · language <b>${esc(LANG_NAME[out.lang] || out.lang)}</b> · planner ${esc(provider)}${out.ms !== undefined ? ` · ${out.ms} ms` : ""}` +
      (out.warnings && out.warnings.length ? `<br><span style="color:#7a4a00">${esc(out.warnings.join("; "))}</span>` : "");
    $("acts").innerHTML = out.actions.length
      ? out.actions.map((a) => `<span class="${a.result.ok ? "" : "err"}">${esc(a.tool)}(${esc(Object.entries(a.args).map(([k, v]) => `${k}=${v}`).join(", "))})</span>`).join("")
      : `<span class="err">no action</span>`;
    $("reply").textContent = out.reply;
    $("reply").lang = BCP47[out.lang] || "en-IN";
    const raw = out.actions.map((a) => ({ tool: a.tool, args: a.args, result: a.result }));
    $("raw").textContent = JSON.stringify(raw, null, 2);
    lastReply = { text: out.reply, lang: out.lang, audio_b64: out.audio_b64 || null };
    $("replay").disabled = false;
  }

  // --------------------------------------------------------------- voice
  function pickVoice(lang) {
    const voices = window.speechSynthesis ? speechSynthesis.getVoices() : [];
    const want = BCP47[lang] || "hi-IN";
    return voices.find((v) => v.lang === want) || voices.find((v) => v.lang && v.lang.toLowerCase().startsWith(want.slice(0, 2))) || null;
  }
  function speak() {
    if (!lastReply) return;
    // Backend with real TTS: play its WAV (mock mode returns a short chime, so prefer the browser voice then)
    if (backend && lastReply.audio_b64 && backendModes && backendModes.tts === "sarvam") {
      if (audioEl) audioEl.pause();
      audioEl = new Audio("data:audio/wav;base64," + lastReply.audio_b64);
      audioEl.play().catch(() => {});
      $("voicenote").textContent = "Voice: Sarvam Bulbul (from your backend).";
      return;
    }
    if (!("speechSynthesis" in window)) { $("voicenote").textContent = "This browser has no speech synthesis; read the reply above."; return; }
    speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(lastReply.text);
    u.lang = BCP47[lastReply.lang] || "hi-IN";
    const v = pickVoice(lastReply.lang);
    if (v) u.voice = v;
    u.rate = 1.0;
    speechSynthesis.speak(u);
    $("voicenote").textContent = v
      ? `Voice: ${v.name} (browser speech). The real box uses Sarvam Bulbul.`
      : `This browser has no ${LANG_NAME[lastReply.lang] || ""} voice installed, so the reply may be silent or read in another accent. The real box uses Sarvam Bulbul.`;
  }
  if ("speechSynthesis" in window) speechSynthesis.onvoiceschanged = () => {};
  $("replay").addEventListener("click", speak);

  // Optional speech input (Chrome/Edge/Safari expose webkitSpeechRecognition)
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (SR) {
    $("mic").hidden = false;
    let rec = null;
    $("mic").addEventListener("click", () => {
      if (rec) { rec.stop(); return; }
      rec = new SR();
      const l = $("lang").value;
      rec.lang = BCP47[l === "auto" ? "hi" : l];
      rec.interimResults = false;
      rec.maxAlternatives = 1;
      $("mic").textContent = "⏹ Stop";
      $("micnote").hidden = false;
      $("micnote").textContent = `Listening (${rec.lang}). Browser speech recognition is a stand-in here; the box uses Sarvam Saaras v4 in codemix mode.`;
      rec.onresult = (e) => { $("utter").value = e.results[0][0].transcript; run(); };
      rec.onerror = (e) => { $("micnote").textContent = `Speech recognition stopped: ${e.error}. You can type instead.`; };
      rec.onend = () => { rec = null; $("mic").textContent = "🎤 Speak"; };
      rec.start();
    });
  }

  // ------------------------------------------------------------- tables
  async function getData() {
    const rl = $("rlang").value;
    if (backend) {
      const [snap, summary, rem] = await Promise.all([
        fetch(backend + "/ledger").then((r) => r.json()),
        fetch(backend + "/summary").then((r) => r.json()),
        fetch(backend + "/reminders?lang=" + rl).then((r) => r.json()),
      ]);
      return { snap, summary, rem };
    }
    return { snap: ledger.snapshot(12), summary: ledger.daily_summary({}), rem: ledger.reminders(rl) };
  }
  const istTime = (ts) => {
    const d = new Date(ts);
    return isNaN(d) ? "" : d.toLocaleString("en-IN", { timeZone: "Asia/Kolkata", day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
  };
  async function refresh(actions) {
    let data;
    try { data = await getData(); } catch (e) { setStatus("bad", "Could not read the ledger from the backend: " + e.message); return; }
    const { snap, summary, rem } = data;
    const touched = new Set((actions || []).flatMap((a) => [a.result && a.result.customer, a.result && a.result.item]).filter(Boolean));
    $("tcust").innerHTML = snap.customers.map((c) => {
      const cls = c.balance > 0 ? "owes" : c.balance < 0 ? "adv" : "";
      const label = c.balance < 0 ? `${money(-c.balance)} advance` : money(c.balance);
      return `<tr class="${touched.has(c.name) ? "flash" : ""}"><td>${esc(c.name)}</td><td class="num ${cls}">${label}</td></tr>`;
    }).join("");
    $("titems").innerHTML = snap.items.map((i) =>
      `<tr class="${i.low ? "low" : ""} ${touched.has(i.name) ? "flash" : ""}"><td>${esc(i.name)}${i.low ? " ⚠︎ reorder" : ""}</td><td class="num">${money(i.price)}</td><td class="num">${qty(i.stock)}</td></tr>`).join("");
    const log = [
      ...snap.credit_txns.map((t) => ({ ts: t.ts, text: `${t.kind === "credit" ? "Udhaar" : "Payment"}: ${t.customer}${t.note ? ` (${t.note})` : ""}`, amt: (t.kind === "payment" ? "−" : "+") + money(t.amount) })),
      ...snap.sales.map((s) => ({ ts: s.ts, text: `Sale: ${qty(s.qty)} × ${s.item}${s.customer ? ` (on credit, ${s.customer})` : ""}`, amt: money(s.amount) })),
    ].sort((a, b) => (a.ts < b.ts ? 1 : a.ts > b.ts ? -1 : 0)).slice(0, 12);
    $("tlog").innerHTML = log.length ? log.map((l) => `<tr><td>${esc(istTime(l.ts))}</td><td>${esc(l.text)}</td><td class="num">${esc(l.amt)}</td></tr>`).join("")
      : `<tr><td colspan="3" class="kv">No entries yet.</td></tr>`;
    $("wa").textContent = summary.whatsapp_text;
    $("washare").href = "https://wa.me/?text=" + encodeURIComponent(summary.whatsapp_text);
    $("trem").innerHTML = rem.length ? rem.map((r) =>
      `<tr><td><b>${esc(r.customer)}</b> · ${money(r.balance)}<br><span class="kv">${esc(r.text)}</span></td><td style="text-align:right"><a href="${esc(r.whatsapp_url)}" target="_blank" rel="noopener">Remind ↗</a></td></tr>`).join("")
      : `<tr><td class="kv">Nobody owes anything right now.</td></tr>`;
  }
  $("rlang").addEventListener("change", () => refresh());

  // --------------------------------------------------------- backend mode
  let backendModes = null;
  function setStatus(kind, msg) { const el = $("bstatus"); el.className = "status " + kind; el.textContent = msg; }
  async function connect() {
    let url = $("backend").value.trim().replace(/\/+$/, "");
    if (!url) { $("backend").focus(); return; }
    if (!/^https?:\/\//i.test(url)) url = "http://" + url;
    if (location.protocol === "https:" && url.startsWith("http://") && !/^http:\/\/(localhost|127\.0\.0\.1|\[::1\])(:|\/|$)/i.test(url)) {
      setStatus("bad", "This page is served over HTTPS, so browsers block plain-http servers other than localhost. Use http://localhost:8000 on the same computer, or expose the server over HTTPS (for example a cloudflared or ngrok tunnel).");
      return;
    }
    setStatus("info", "Connecting to " + url + " …");
    try {
      const r = await fetch(url + "/health");
      if (!r.ok) throw new Error("HTTP " + r.status);
      const h = await r.json();
      backend = url; backendModes = h.modes || {};
      localStorage.setItem(BKEY, url);
      setStatus("ok", `Connected to ${url} · STT ${backendModes.stt} · planner ${backendModes.llm} · TTS ${backendModes.tts}${h.shop ? " · " + h.shop : ""}`);
      $("modebadge").textContent = "backend: " + (backendModes.llm || "?");
      $("disconnect").disabled = false;
      refresh();
    } catch (e) {
      setStatus("bad", `Could not reach ${url}/health (${e.message}). Is the server running, and does its CORS_ORIGINS include ${location.origin}?`);
    }
  }
  function disconnect() {
    backend = null; backendModes = null;
    localStorage.removeItem(BKEY);
    setStatus("info", "Mode: in-browser (offline rule parser)");
    $("modebadge").textContent = "in-browser";
    $("disconnect").disabled = true;
    refresh();
  }
  $("connect").addEventListener("click", connect);
  $("disconnect").addEventListener("click", disconnect);
  $("backend").addEventListener("keydown", (e) => { if (e.key === "Enter") connect(); });
  const savedBackend = localStorage.getItem(BKEY);
  if (savedBackend) $("backend").value = savedBackend;

  // ---------------------------------------------------------------- misc
  $("run").addEventListener("click", run);
  $("utter").addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); run(); } });
  $("reset").addEventListener("click", async () => {
    if (backend) {
      try { await fetch(backend + "/reset", { method: "POST" }); } catch (e) { setStatus("bad", "Reset failed: " + e.message); }
    } else {
      ledger.reset(true, true); agent = new K.Agent(ledger); save();
    }
    $("meta").textContent = "Demo data reset."; $("acts").innerHTML = ""; $("reply").textContent = ""; $("raw").textContent = "—";
    refresh();
  });

  refresh();
})();

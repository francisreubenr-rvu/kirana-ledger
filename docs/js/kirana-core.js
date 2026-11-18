/* Kirana Voice Ledger — client-side core.
 *
 * A faithful JavaScript port of the server's offline path so the demo runs entirely in the browser:
 *   server/rule_parser.py  -> parse(), detectLang()
 *   server/ledger.py       -> Ledger (state kept in a plain object, persisted to localStorage by the page)
 *   server/messages.py     -> confirm(), notUnderstood()
 *   server/tools.py        -> runTool()
 *   server/agent.py        -> Agent.handleText()
 * difflib.SequenceMatcher / get_close_matches are ported too, so fuzzy matching behaves the same.
 * tests/js_parity.mjs checks this file against samples/utterances.json and against the Python code.
 */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.Kirana = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  // ------------------------------------------------------------------ helpers
  const S = (arr) => new Set(arr);
  const union = (...sets) => { const o = new Set(); for (const s of sets) for (const x of s) o.add(x); return o; };
  const minus = (a, b) => new Set([...a].filter((x) => !b.has(x)));
  const inter = (a, b) => new Set([...a].filter((x) => b.has(x)));
  const any = (a, b) => { for (const x of a) if (b.has(x)) return true; return false; };
  const stripChars = (s, chars) => {
    let i = 0, j = s.length;
    while (i < j && chars.includes(s[i])) i++;
    while (j > i && chars.includes(s[j - 1])) j--;
    return s.slice(i, j);
  };
  const isAscii = (s) => /^[\x00-\x7f]*$/.test(s);
  const has = (o, k) => Object.prototype.hasOwnProperty.call(o, k);

  // --------------------------------------------------------------- vocabulary
  const NATIVE = {
    "उधार": "udhaar", "उधारी": "udhaar", "का": "ka", "के": "ke", "की": "ki", "को": "ko", "ने": "ne", "से": "se",
    "दिए": "diye", "दिये": "diye", "दिया": "diya", "जमा": "jama", "वापस": "wapas", "बिक": "bik", "गए": "gaye",
    "गये": "gaye", "गया": "gaya", "बिके": "bike", "बेचा": "becha", "बेचे": "beche", "आया": "aaya", "आए": "aaye",
    "आये": "aaye", "बाकी": "baaki", "बाक़ी": "baaki", "कितना": "kitna", "कितने": "kitne", "हिसाब": "hisaab",
    "आज": "aaj", "और": "aur", "रुपये": "rupaye", "रुपए": "rupaye", "है": "hai", "हैं": "hain", "स्टॉक": "stock",
    "माल": "maal", "लिख": "likh", "दो": "do", "लिखो": "likho",
    "ಸಾಲ": "saala", "ಕೊಟ್ಟರು": "kottru", "ಕೊಟ್ಟಿದ್ದಾರೆ": "kottidaare", "ಮಾರಾಟ": "maarata",
    "ಮಾರಾಟವಾಯಿತು": "maarata", "ಮಾರಿದೆ": "maaride", "ಬಾಕಿ": "baaki", "ಎಷ್ಟು": "eshtu", "ಬಂದಿದೆ": "bandide",
    "ಇಂದಿನ": "indina", "ಲೆಕ್ಕ": "lekka", "ಮತ್ತು": "mattu", "ರೂಪಾಯಿ": "rupaye", "ಅವರಿಗೆ": "avarige",
    "ಸ್ಟಾಕ್": "stock", "ಬರೆಯಿರಿ": "bareyiri",
    "கடன்": "kadan", "கொடுத்தார்": "kuduthaar", "கொடுத்தாங்க": "kuduthanga", "விற்றது": "vithuchu",
    "வித்துச்சு": "vithuchu", "பாக்கி": "baaki", "எவ்வளவு": "evvalavu", "வந்தது": "vandhuchu",
    "வந்துச்சு": "vandhuchu", "இன்றைய": "indraiya", "கணக்கு": "kanakku", "ரூபாய்": "rupaye", "மற்றும்": "and",
    "ஸ்டாக்": "stock",
  };

  const SUMMARY_KW = S(["hisaab", "hisab", "summary", "lekka", "kanakku", "report", "total"]);
  const DAY_KW = S(["aaj", "today", "indina", "indu", "ivattu", "indraiya", "inniki", "din", "day"]);
  const QUERY_KW = S(["kitna", "kitne", "baaki", "baki", "balance", "eshtu", "evvalavu", "owes", "owe", "due", "paakki"]);
  const PAYMENT_KW = S(["diye", "diya", "jama", "wapas", "vapas", "paid", "pay", "chukaya", "kottru", "kottaru", "kottidaare",
    "kottidare", "vaapas", "kuduthaar", "kuduthanga", "kuduthaanga", "kuduthar", "returned", "lautaye"]);
  const CREDIT_KW = S(["udhaar", "udhar", "udhari", "udhaari", "credit", "likh", "likho", "khata", "khate", "saala", "saal",
    "kadan", "bareyiri", "bari"]);
  const STOCK_KW = S(["aaya", "aaye", "aayi", "stock", "maal", "restock", "bandide", "bandhide", "banthu", "bantu",
    "vandhuchu", "vanthuchu", "vandhathu", "arrived", "received", "came"]);
  const STOCK_REMOVE_KW = S(["hatao", "hata", "nikalo", "remove", "kharab", "expired", "expire", "damage", "damaged", "toota", "tooti", "phenk", "waste"]);
  const SALE_KW = S(["bik", "bika", "biki", "bike", "becha", "bechi", "beche", "bech", "sold", "sale", "maaratu", "maaride",
    "maarata", "maaraata", "vittachu", "vithuchu", "vitrom", "vithom", "vikkapattathu", "gaya", "gaye"]);
  const SALE_STRONG = minus(SALE_KW, S(["gaya", "gaye"]));

  const PARTICLES = S(["ka", "ke", "ki", "ko", "ne", "se", "ge", "ige", "avarige", "avru", "avaru", "kku", "ku", "ukku",
    "oda", "udaya", "du", "dhu", "avanga", "ji", "anna", "bhai", "akka", "amma", "sir", "madam", "to", "for",
    "from", "has", "of"]);
  const FILLER = S(["hai", "hain", "ho", "hua", "hue", "kar", "karo", "kiya", "kiye", "do", "de", "diya", "the", "tha", "mein",
    "me", "aur", "and", "mattu", "matthu", "um", "a", "an", "is", "packet", "pack", "pcs", "piece", "pieces",
    "rupaye", "rupees", "rupay", "rs", "inr", "ne", "gaye", "gaya", "ge", "mein", "naya", "new", "add", "ide",
    "aagide", "aaytu", "achu", "irukku", "kodi", "kudu", "please", "bhi", "agaya", "liya", "li", "le", "liye",
    "now", "ab", "abhi", "bareyiri", "likh", "likho", "become", "today", "aaj"]);

  const NUM_WORDS = {
    ek: 1, do: 2, teen: 3, char: 4, chaar: 4, paanch: 5, panch: 5, chhe: 6, chhah: 6, saat: 7,
    aath: 8, nau: 9, das: 10, ondu: 1, eradu: 2, mooru: 3, naalku: 4, aidu: 5, elu: 7, entu: 8,
    hattu: 10, onnu: 1, rendu: 2, moonu: 3, naalu: 4, anju: 5, ezhu: 7, ettu: 8, pathu: 10,
    one: 1, two: 2, three: 3, four: 4, five: 5, six: 6, seven: 7, eight: 8, nine: 9, ten: 10,
  };

  const KN_HINTS = S(["saala", "kottru", "kottaru", "kottidaare", "maaratu", "maaride", "maarata", "eshtu", "bandide", "ge",
    "avarige", "indina", "lekka", "mattu", "matthu", "bareyiri", "ige", "avru"]);
  const TA_HINTS = S(["kadan", "kuduthaar", "kuduthanga", "vittachu", "vithuchu", "evvalavu", "vandhuchu", "ukku", "kku",
    "kanakku", "indraiya", "paakki", "inniki"]);
  const HI_HINTS = S(["ka", "ke", "ki", "ko", "ne", "udhaar", "udhar", "diye", "jama", "bik", "gaye", "aaya", "kitna", "hisaab",
    "aaj", "hai"]);
  const EN_HINTS = S(["sold", "paid", "credit", "owes", "arrived", "received", "how", "much", "summary", "today"]);

  const NUM_RE = /^\d+(?:\.\d+)?$/;
  const TOKEN_SRC = "[^\\s,;:!?।()\"']+";
  const CURRENCY_TOKENS = S(["rs", "rs.", "₹", "rupaye", "rupees", "rupay", "inr", "rupaiye"]);
  const SIZE_UNITS_NUM = S(["kg", "g", "gm", "ml", "l", "ltr", "litre", "liter", "gram"]);
  const SIZE_UNITS_ITEM = S(["kg", "g", "ml", "l", "ltr", "gm"]);
  const PARTICLE_AFTER_NAME = S(["ka", "ke", "ki", "ko", "ne", "se", "ge", "ige", "avarige", "avru", "avaru", "kku", "ku", "ukku",
    "oda", "du", "dhu", "avanga", "ji"]);

  const findTokens = (text) => text.match(new RegExp(TOKEN_SRC, "g")) || [];

  function tokens(text) {
    text = text.split("₹").join(" ₹ ");
    const out = [];
    for (let t of findTokens(text)) {
      t = stripChars(t, ".-");
      if (!t) continue;
      t = has(NATIVE, t) ? NATIVE[t] : t;
      out.push(t.toLowerCase());
    }
    return out;
  }

  function detectLang(text) {
    if (/[\u0C80-\u0CFF]/.test(text)) return "kn";
    if (/[\u0B80-\u0BFF]/.test(text)) return "ta";
    if (/[\u0900-\u097F]/.test(text)) return "hi";
    const toks = new Set(tokens(text));
    for (const t of [...toks]) {
      if (/^[a-z]{3,}(ge|ige)$/.test(t)) toks.add("ge");
      if (/^[a-z]{3,}(kku|ukku)$/.test(t)) toks.add("kku");
    }
    const scores = { kn: inter(toks, KN_HINTS).size, ta: inter(toks, TA_HINTS).size, hi: inter(toks, HI_HINTS).size, en: inter(toks, EN_HINTS).size };
    // Python: max(scores, key=(score, k=="hi")) -> first key in insertion order with the max key tuple
    let best = null, bestKey = null;
    for (const k of ["kn", "ta", "hi", "en"]) {
      const key = [scores[k], k === "hi" ? 1 : 0];
      if (best === null || key[0] > bestKey[0] || (key[0] === bestKey[0] && key[1] > bestKey[1])) { best = k; bestKey = key; }
    }
    return scores[best] > 0 ? best : "hi";
  }

  function splitClauses(text) {
    const re = /[,;।\n]|\.(?!\d)|\s(?:aur|and|mattu|matthu|innu|phir|then|अउर|और|ಮತ್ತು|மற்றும்)\s/i;
    return text.split(re).map((p) => (p || "").trim()).filter((p) => p);
  }

  function numbers(toks) {
    const nums = []; let amount = null;
    toks.forEach((t, i) => {
      if (t.startsWith("₹") && NUM_RE.test(t.slice(1) || "x")) { amount = parseFloat(t.slice(1)); return; }
      if (NUM_RE.test(t)) {
        if (i + 1 < toks.length && SIZE_UNITS_NUM.has(toks[i + 1])) return;
        const prevCur = i > 0 && CURRENCY_TOKENS.has(toks[i - 1]);
        const nextCur = i + 1 < toks.length && CURRENCY_TOKENS.has(toks[i + 1]);
        if (prevCur || nextCur) amount = parseFloat(t);
        else nums.push([i, parseFloat(t)]);
      }
    });
    return [nums, amount];
  }

  const title = (s) => (isAscii(s) ? s.slice(0, 1).toUpperCase() + s.slice(1) : s);

  function findName(toks, orig, known, skip) {
    const knownL = new Map();
    for (const k of known) knownL.set(k.toLowerCase(), k);
    const vocab = union(SUMMARY_KW, QUERY_KW, PAYMENT_KW, CREDIT_KW, STOCK_KW, SALE_KW, PARTICLES, FILLER, DAY_KW, skip);
    for (const t of toks) {
      if (knownL.has(t)) return knownL.get(t);
      const m = /^([a-z]{3,}?)-?(ge|ige|kku|ukku|ku|ka|ki|ke|ko|ne|du|dhu|oda)$/.exec(t);
      if (m && knownL.has(m[1])) return knownL.get(m[1]);
    }
    for (let i = 1; i < toks.length; i++) {
      if (PARTICLE_AFTER_NAME.has(toks[i])) {
        const cand = toks[i - 1];
        if (!vocab.has(cand) && !NUM_RE.test(cand) && !cand.startsWith("₹")) return title(orig[i - 1]);
      }
    }
    for (const t of toks) {
      const m = /^([a-z]{3,}?)-?(ige|ge|ukku|kku)$/.exec(t);
      if (m && !vocab.has(t)) return title(m[1]);
    }
    return null;
  }

  function itemText(toks, orig, dropIdx, name) {
    const vocab = union(SUMMARY_KW, QUERY_KW, PAYMENT_KW, CREDIT_KW, STOCK_KW, SALE_KW, STOCK_REMOVE_KW, PARTICLES, FILLER);
    const words = [];
    toks.forEach((t, i) => {
      if (dropIdx.has(i) || vocab.has(t) || CURRENCY_TOKENS.has(t) || t.startsWith("₹")) return;
      if (name && t === name.toLowerCase()) return;
      if (NUM_RE.test(t) && !(i + 1 < toks.length && SIZE_UNITS_ITEM.has(toks[i + 1]))) return;
      words.push(orig[i]);
    });
    return words.join(" ").trim();
  }

  /** Utterance -> {lang, calls:[{tool, args}]}. Same behaviour as server/rule_parser.py parse(). */
  function parse(text, knownCustomers, itemLookup) {
    const lang = detectLang(text);
    const known = [...(knownCustomers || [])];
    const calls = [];
    for (const clause of splitClauses(text)) {
      let orig = findTokens(clause.split("₹").join(" ₹ ")).map((o) => stripChars(o, ".-")).filter((o) => o);
      const toks = tokens(clause);
      if (orig.length !== toks.length) orig = toks.slice();
      orig = orig.map((o) => (has(NATIVE, o) ? NATIVE[o] : o));
      const tset = new Set(toks);
      const [nums, curAmount] = numbers(toks);
      const name = findName(toks, orig, known, new Set());

      if ((any(tset, SUMMARY_KW) && (any(tset, DAY_KW) || !name)) || tset.has("summary")) {
        calls.push({ tool: "daily_summary", args: {} }); continue;
      }
      if (any(tset, QUERY_KW) && name && !nums.length && curAmount === null && !any(tset, minus(CREDIT_KW, S(["baaki"])))) {
        calls.push({ tool: "query_balance", args: { customer: name } }); continue;
      }
      const amount = curAmount !== null ? curAmount : (nums.length ? nums[0][1] : null);

      const strongPay = any(tset, minus(PAYMENT_KW, S(["diye", "diya"])));
      if (name && amount !== null && (strongPay || (any(tset, PAYMENT_KW) && !any(tset, CREDIT_KW)))) {
        calls.push({ tool: "record_payment", args: { customer: name, amount } }); continue;
      }
      const isCredit = any(tset, CREDIT_KW);
      const isSale = any(tset, SALE_STRONG) || (any(tset, S(["gaya", "gaye"])) && !any(tset, STOCK_KW));
      const isStock = any(tset, STOCK_KW) || any(tset, STOCK_REMOVE_KW);

      let qty = null, drop = new Set();
      if (curAmount !== null && nums.length) { qty = nums[0][1]; drop = new Set([nums[0][0]]); }
      else if (nums.length && (isSale || isStock || (isCredit && nums.length > 0))) { qty = nums[0][1]; drop = new Set([nums[0][0]]); }
      if (qty === null) {
        const stop = union(FILLER, CREDIT_KW, PARTICLES);
        for (let i = 0; i < toks.length; i++) {
          if (has(NUM_WORDS, toks[i]) && i + 1 < toks.length && !stop.has(toks[i + 1])) { qty = NUM_WORDS[toks[i]]; drop = new Set([i]); break; }
        }
      }
      const item = itemText(toks, orig, drop, name);
      const knownItem = item && itemLookup ? itemLookup(item) : null;

      if (isCredit && name) {
        if (knownItem && (curAmount !== null || (qty !== null && qty < 50))) {
          const args = { item: knownItem, qty: qty || 1, customer: name };
          if (curAmount !== null) args.amount = curAmount;
          calls.push({ tool: "record_sale", args });
        } else if (amount !== null) {
          calls.push({ tool: "add_credit", args: { customer: name, amount } });
        }
        continue;
      }
      if (isStock && item) {
        let q = qty !== null ? qty : 1;
        if (any(tset, STOCK_REMOVE_KW)) q = -Math.abs(q);
        calls.push({ tool: "update_stock", args: { item: knownItem || item, qty: q } }); continue;
      }
      if (isSale && item) {
        const args = { item: knownItem || item, qty: qty !== null ? qty : 1 };
        if (curAmount !== null) args.amount = curAmount;
        calls.push({ tool: "record_sale", args }); continue;
      }
    }
    return { lang, calls };
  }

  // ------------------------------------------------------------ difflib port
  function matchingBlocks(a, b) {
    const b2j = new Map();
    for (let j = 0; j < b.length; j++) { const c = b[j]; if (!b2j.has(c)) b2j.set(c, []); b2j.get(c).push(j); }
    // autojunk only applies when len(b) >= 200; our strings are short, but keep the rule
    if (b.length >= 200) {
      const ntest = Math.floor(b.length / 100) + 1;
      for (const [c, idx] of [...b2j]) if (idx.length > ntest) b2j.delete(c);
    }
    const longest = (alo, ahi, blo, bhi) => {
      let besti = alo, bestj = blo, bestsize = 0;
      let j2len = new Map();
      for (let i = alo; i < ahi; i++) {
        const newj2len = new Map();
        for (const j of b2j.get(a[i]) || []) {
          if (j < blo) continue;
          if (j >= bhi) break;
          const k = (j2len.get(j - 1) || 0) + 1;
          newj2len.set(j, k);
          if (k > bestsize) { besti = i - k + 1; bestj = j - k + 1; bestsize = k; }
        }
        j2len = newj2len;
      }
      return [besti, bestj, bestsize];
    };
    const queue = [[0, a.length, 0, b.length]], blocks = [];
    while (queue.length) {
      const [alo, ahi, blo, bhi] = queue.pop();
      const [i, j, k] = longest(alo, ahi, blo, bhi);
      if (k) {
        blocks.push([i, j, k]);
        if (alo < i && blo < j) queue.push([alo, i, blo, j]);
        if (i + k < ahi && j + k < bhi) queue.push([i + k, ahi, j + k, bhi]);
      }
    }
    blocks.sort((x, y) => x[0] - y[0] || x[1] - y[1]);
    return blocks;
  }
  function ratio(a, b) {
    a = [...a]; b = [...b];
    const t = a.length + b.length;
    if (!t) return 1.0;
    const m = matchingBlocks(a, b).reduce((s, x) => s + x[2], 0);
    return (2.0 * m) / t;
  }
  function getCloseMatches(word, possibilities, n, cutoff) {
    const res = [];
    for (const x of possibilities) { const r = ratio(x, word); if (r >= cutoff) res.push([r, x]); }
    res.sort((p, q) => q[0] - p[0] || (q[1] > p[1] ? 1 : q[1] < p[1] ? -1 : 0));
    return res.slice(0, n).map((x) => x[1]);
  }

  // ------------------------------------------------------------------ ledger
  const DEMO_ITEMS = [
    ["Aashirvaad Atta 5kg", "aashirvaad|ashirvad|aashirvad|atta|आशीर्वाद|ಆಶೀರ್ವಾದ|ஆசீர்வாத்", "pack", 285, 12, 3],
    ["Maggi Noodles", "maggi|मैगी|ಮ್ಯಾಗಿ|மேகி", "pack", 14, 40, 10],
    ["Parle-G", "parle|parle g|parleg|biscuit|पारले|ಪಾರ್ಲೆ|பார்லே", "pack", 10, 50, 10],
    ["Amul Milk 500ml", "milk|doodh|amul|दूध|ಹಾಲು|haalu|பால்|paal", "packet", 27, 20, 5],
    ["Tata Salt 1kg", "salt|namak|tata salt|नमक|ಉಪ್ಪು|uppu|உப்பு", "pack", 28, 15, 4],
    ["Fortune Sunflower Oil 1L", "oil|tel|fortune|तेल|ಎಣ್ಣೆ|enne|எண்ணெய்|ennai", "pouch", 155, 10, 3],
    ["Toor Dal 1kg", "dal|daal|toor|tur|दाल|ಬೇಳೆ|bele|பருப்பு|paruppu", "kg", 160, 8, 3],
    ["Sugar 1kg", "sugar|cheeni|chini|shakkar|चीनी|ಸಕ್ಕರೆ|sakkare|சர்க்கரை|sakkarai", "kg", 46, 10, 3],
    ["Surf Excel 1kg", "surf|surf excel|detergent|सर्फ", "pack", 140, 6, 2],
  ];
  const DEMO_CUSTOMERS = ["Ramesh", "Lakshmi", "Suresh", "Fatima", "Murugan"];
  const DEMO_OPENING = [["Lakshmi", 1200], ["Suresh", 350]];
  const IST_MS = 5.5 * 3600 * 1000;
  const DAY_MS = 86400000;

  const istDate = (ms) => new Date(ms + IST_MS).toISOString().slice(0, 10);
  const istIso = (ms) => new Date(ms + IST_MS).toISOString().replace("Z", "+05:30");
  const rs = (p) => (p === null || p === undefined ? null : Math.round(p) / 100);
  const paise = (r) => Math.round(parseFloat(r) * 100);
  const fmtRs = (p) => { const r = p / 100; return Number.isInteger(r) ? "₹" + group(r, 0) : "₹" + group(r, 2); };
  const fmtQty = (q) => (Number.isInteger(Number(q)) ? String(Number(q)) : String(Number(q)));
  function group(x, digits) {
    return Number(x).toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
  }
  function phon(s) {
    s = s.toLowerCase().trim();
    for (const [a, b] of [["ksh", "x"], ["ks", "x"], ["sh", "s"], ["th", "t"], ["dh", "d"], ["bh", "b"], ["kh", "k"],
      ["gh", "g"], ["ph", "f"], ["w", "v"], ["ee", "i"], ["oo", "u"], ["aa", "a"], ["z", "j"]]) s = s.split(a).join(b);
    return s.replace(/(.)\1+/gu, "$1");
  }
  const norm = (s) => s.toLowerCase().replace(/[^\p{L}\p{N}_\s]/gu, " ").replace(/\s+/gu, " ").trim();
  const nocase = (a, b) => a.replace(/[A-Z]/g, (c) => c.toLowerCase()) === b.replace(/[A-Z]/g, (c) => c.toLowerCase());

  class LedgerError extends Error {}

  class Ledger {
    constructor(state, opts) {
      opts = opts || {};
      this.shopName = opts.shopName || "Sri Lakshmi Kirana";
      this.now = opts.now || (() => Date.now());
      this.lowStockDefault = 3;
      this.s = state || Ledger.emptyState();
    }
    static emptyState() { return { seq: 1, customers: [], txns: [], items: [], sales: [], moves: [] }; }
    _id() { return this.s.seq++; }
    toJSON() { return this.s; }

    seedDemo(openingBalances) {
      for (const [name, aliases, unit, price, stock, reorder] of DEMO_ITEMS) {
        if (!this.s.items.some((i) => nocase(i.name, name)))
          this.s.items.push({ id: this._id(), name, aliases, unit, price_paise: price * 100, stock_qty: stock, reorder_level: reorder });
      }
      for (const name of DEMO_CUSTOMERS) {
        if (!this.s.customers.some((c) => nocase(c.name, name)))
          this.s.customers.push({ id: this._id(), name, phone: null, created_at: this.now() });
      }
      if (openingBalances && !this.s.txns.length) {
        const y = this.now() - DAY_MS;
        for (const [name, amt] of DEMO_OPENING) {
          const c = this.s.customers.find((x) => x.name === name);
          this.s.txns.push({ id: this._id(), customer_id: c.id, kind: "credit", amount_paise: amt * 100, note: "opening balance (paper khata)", ts: y });
        }
      }
    }
    reset(seed = true, opening = true) {
      this.s = Ledger.emptyState();
      if (seed) this.seedDemo(opening);
    }

    _findCustomer(name, create) {
      name = name.trim();
      if (!name) throw new LedgerError("customer name is empty");
      const exact = this.s.customers.find((c) => nocase(c.name, name));
      if (exact) return exact;
      const names = new Map();
      for (const c of this.s.customers) names.set(c.name.toLowerCase(), c);
      const close = getCloseMatches(name.toLowerCase(), [...names.keys()], 1, 0.8);
      if (close.length) return names.get(close[0]);
      const key = phon(name);
      for (const [n, c] of names) {
        if (phon(n) === key || (key.length >= 5 && ratio(phon(n), key) >= 0.88)) return c;
      }
      if (!create) return null;
      const clean = name.slice(0, 1).toUpperCase() + name.slice(1);
      const c = { id: this._id(), name: clean, phone: null, created_at: this.now() };
      this.s.customers.push(c);
      return c;
    }
    findItem(name) {
      const q = norm(name);
      if (!q) return null;
      let best = null, bestScore = 0;
      for (const r of this.s.items) {
        const cands = [norm(r.name)].concat(r.aliases.split("|").filter((a) => a).map(norm));
        for (const c of cands) {
          if (!c) continue;
          let score;
          if (q === c) score = 1.0;
          else if (q.split(" ").includes(c) || (c.length > 3 && q.includes(c)) || (q.length > 3 && c.includes(q))) score = 0.9;
          else score = ratio(q, c);
          if (score > bestScore) { best = r; bestScore = score; }
        }
      }
      return bestScore >= 0.75 ? best : null;
    }
    _balance(cid) {
      return this.s.txns.filter((t) => t.customer_id === cid).reduce((s, t) => s + (t.kind === "credit" ? t.amount_paise : -t.amount_paise), 0);
    }
    static _positive(amount, what = "amount") {
      const v = typeof amount === "number" ? amount : (typeof amount === "string" && amount.trim() !== "" ? Number(amount) : NaN);
      if (!Number.isFinite(v)) throw new LedgerError(`${what} must be a number, got ${JSON.stringify(amount)}`);
      const p = Math.round(v * 100);
      if (p <= 0) throw new LedgerError(`${what} must be positive`);
      return p;
    }
    static _num(x, what) {
      const v = typeof x === "number" ? x : (typeof x === "string" && x.trim() !== "" ? Number(x) : NaN);
      if (!Number.isFinite(v)) throw new LedgerError(`${what} must be a number, got ${JSON.stringify(x)}`);
      return v;
    }

    add_credit({ customer, amount, note }) {
      const p = Ledger._positive(amount);
      const c = this._findCustomer(customer, true);
      this.s.txns.push({ id: this._id(), customer_id: c.id, kind: "credit", amount_paise: p, note: note || null, ts: this.now() });
      return { ok: true, action: "add_credit", customer: c.name, amount: rs(p), balance: rs(this._balance(c.id)) };
    }
    record_payment({ customer, amount }) {
      const p = Ledger._positive(amount);
      const c = this._findCustomer(customer, false);
      if (!c) throw new LedgerError(`no customer named '${customer}' in the ledger`);
      this.s.txns.push({ id: this._id(), customer_id: c.id, kind: "payment", amount_paise: p, note: null, ts: this.now() });
      return { ok: true, action: "record_payment", customer: c.name, amount: rs(p), balance: rs(this._balance(c.id)) };
    }
    record_sale({ item, qty = 1, amount, customer }) {
      const q = Ledger._num(qty, "qty");
      if (q <= 0) throw new LedgerError("qty must be positive");
      const it = this.findItem(item);
      let amt = null;
      if (amount !== undefined && amount !== null) amt = Ledger._positive(amount);
      else if (it && it.price_paise !== null) amt = Math.round(it.price_paise * q);
      const ts = this.now();
      const cust = customer ? this._findCustomer(customer, true) : null;
      const name = it ? it.name : String(item).trim();
      this.s.sales.push({ id: this._id(), item_id: it ? it.id : null, item_name: name, qty: q, amount_paise: amt, customer_id: cust ? cust.id : null, ts });
      let stock = null, low = null;
      if (it) {
        it.stock_qty -= q;
        this.s.moves.push({ id: this._id(), item_id: it.id, delta: -q, reason: "sale", ts });
        stock = it.stock_qty; low = stock <= it.reorder_level;
      }
      let bal = null;
      if (cust && amt) {
        this.s.txns.push({ id: this._id(), customer_id: cust.id, kind: "credit", amount_paise: amt, note: `${fmtQty(q)} x ${name}`, ts });
        bal = this._balance(cust.id);
      }
      const out = { ok: true, action: "record_sale", item: name, known_item: !!it, qty: q, amount: rs(amt), stock_left: stock, low_stock: !!low };
      if (cust) { out.customer = cust.name; out.balance = rs(bal); }
      return out;
    }
    update_stock({ item, qty, price, unit }) {
      const q = Ledger._num(qty, "qty");
      let it = this.findItem(item), created = false;
      if (!it) {
        if (q < 0) throw new LedgerError(`unknown item '${item}'`);
        it = { id: this._id(), name: String(item).trim(), aliases: "", unit: unit || "pc", price_paise: price ? paise(price) : null, stock_qty: 0, reorder_level: this.lowStockDefault };
        this.s.items.push(it); created = true;
      } else if (price) it.price_paise = paise(price);
      it.stock_qty += q;
      this.s.moves.push({ id: this._id(), item_id: it.id, delta: q, reason: q >= 0 ? "restock" : "adjust", ts: this.now() });
      return { ok: true, action: "update_stock", item: it.name, delta: q, stock: it.stock_qty, created, low_stock: it.stock_qty <= it.reorder_level };
    }
    query_balance({ customer }) {
      const c = this._findCustomer(customer, false);
      if (!c) return { ok: true, action: "query_balance", customer: customer.trim(), known: false, balance: 0.0 };
      const mine = this.s.txns.filter((t) => t.customer_id === c.id);
      return { ok: true, action: "query_balance", customer: c.name, known: true, balance: rs(this._balance(c.id)), last_txn: mine.length ? istIso(mine[mine.length - 1].ts) : null };
    }
    daily_summary({ day } = {}) {
      const d = day || istDate(this.now());
      const sameDay = (ts) => istDate(ts) === d;
      const sales = this.s.sales.filter((x) => sameDay(x.ts));
      const total = sales.reduce((s, x) => s + (x.amount_paise || 0), 0);
      const cash = sales.filter((x) => x.customer_id === null).reduce((s, x) => s + (x.amount_paise || 0), 0);
      const byItem = new Map();
      for (const x of sales) { const e = byItem.get(x.item_name) || { item: x.item_name, q: 0, a: 0 }; e.q += x.qty; e.a += x.amount_paise || 0; byItem.set(x.item_name, e); }
      const top = [...byItem.values()].sort((a, b) => b.a - a.a).slice(0, 3);
      const kinds = { credit: 0, payment: 0 };
      for (const t of this.s.txns) if (sameDay(t.ts)) kinds[t.kind] += t.amount_paise;
      const low = this.s.items.filter((i) => i.stock_qty <= i.reorder_level).sort((a, b) => a.stock_qty - b.stock_qty);
      const debtors = this.outstanding();
      const outstandingP = debtors.reduce((s, x) => s + paise(x.balance), 0);
      const sm = {
        ok: true, action: "daily_summary", date: d, sales_count: sales.length, sales_total: rs(total), cash_sales: rs(cash),
        credit_given: rs(kinds.credit), payments_received: rs(kinds.payment), outstanding_total: rs(outstandingP),
        top_items: top.map((t) => ({ item: t.item, qty: t.q, amount: rs(t.a) })),
        low_stock: low.map((i) => ({ item: i.name, stock: i.stock_qty })),
        top_debtors: debtors.slice(0, 5),
      };
      sm.whatsapp_text = this._summaryText(sm);
      return sm;
    }
    outstanding() {
      const out = [];
      for (const c of this.s.customers) {
        const mine = this.s.txns.filter((t) => t.customer_id === c.id);
        if (!mine.length) continue;
        const bal = this._balance(c.id);
        if (bal > 0) out.push({ customer: c.name, phone: c.phone, balance: rs(bal), last_txn: istIso(Math.max(...mine.map((t) => t.ts))) });
      }
      return out.sort((a, b) => b.balance - a.balance);
    }
    reminders(lang = "hi") {
      return this.outstanding().map((d) => {
        const text = (REMINDER_TEMPLATES[lang] || REMINDER_TEMPLATES.hi)
          .replace("{name}", d.customer).replace("{amt}", fmtRs(paise(d.balance))).replace("{shop}", this.shopName);
        const phone = (d.phone || "").replace(/\D/g, "");
        return { ...d, text, whatsapp_url: `https://wa.me/${phone ? phone : ""}?text=${encodeURIComponent(text)}` };
      });
    }
    snapshot(limit = 20) {
      const cname = (id) => { const c = this.s.customers.find((x) => x.id === id); return c ? c.name : null; };
      const customers = this.s.customers.map((c) => ({ name: c.name, phone: c.phone, balance: rs(this._balance(c.id)) }))
        .sort((a, b) => b.balance - a.balance || (a.name < b.name ? -1 : a.name > b.name ? 1 : 0));
      return {
        customers,
        items: [...this.s.items].sort((a, b) => (a.name < b.name ? -1 : a.name > b.name ? 1 : 0))
          .map((r) => ({ name: r.name, unit: r.unit, price: rs(r.price_paise), stock: r.stock_qty, low: r.stock_qty <= r.reorder_level })),
        sales: [...this.s.sales].reverse().slice(0, limit)
          .map((r) => ({ item: r.item_name, qty: r.qty, amount: rs(r.amount_paise), customer: cname(r.customer_id), ts: istIso(r.ts) })),
        credit_txns: [...this.s.txns].reverse().slice(0, limit)
          .map((r) => ({ customer: cname(r.customer_id), kind: r.kind, amount: rs(r.amount_paise), note: r.note, ts: istIso(r.ts) })),
      };
    }
    _summaryText(s) {
      const lines = [
        `*${this.shopName} — ${s.date}*`,
        `Sales: ${s.sales_count} bill${s.sales_count === 1 ? "" : "s"}, ${fmtRs(paise(s.sales_total))} (cash ${fmtRs(paise(s.cash_sales))})`,
        `Udhaar given: ${fmtRs(paise(s.credit_given))} | Collected: ${fmtRs(paise(s.payments_received))}`,
        `Total outstanding: ${fmtRs(paise(s.outstanding_total))}`,
      ];
      if (s.top_items.length) lines.push("Top items: " + s.top_items.map((t) => `${t.item} x${fmtQty(t.qty)}`).join(", "));
      if (s.low_stock.length) lines.push("Reorder: " + s.low_stock.map((t) => `${t.item} (${fmtQty(t.stock)} left)`).join(", "));
      if (s.top_debtors.length) lines.push("Biggest dues: " + s.top_debtors.slice(0, 3).map((d) => `${d.customer} ${fmtRs(paise(d.balance))}`).join(", "));
      return lines.join("\n");
    }
  }

  const REMINDER_TEMPLATES = {
    hi: "Namaste {name} ji 🙏 {shop} mein aapka {amt} udhaar baaki hai. Suvidha ho to jama kar dijiye. Dhanyavaad!",
    kn: "ನಮಸ್ಕಾರ {name} ಅವರೇ 🙏 {shop} ಅಂಗಡಿಯಲ್ಲಿ ನಿಮ್ಮ {amt} ಬಾಕಿ ಇದೆ. ಅನುಕೂಲವಾದಾಗ ಪಾವತಿಸಿ. ಧನ್ಯವಾದಗಳು!",
    ta: "வணக்கம் {name} 🙏 {shop} கடையில் உங்கள் {amt} பாக்கி உள்ளது. வசதிப்படும்போது செலுத்தவும். நன்றி!",
    en: "Hello {name} 🙏 You have {amt} pending at {shop}. Please clear it when convenient. Thank you!",
  };

  // ---------------------------------------------------------------- tools
  const TOOL_PARAMS = {
    add_credit: ["customer", "amount", "note"],
    record_payment: ["customer", "amount"],
    record_sale: ["item", "qty", "amount", "customer"],
    update_stock: ["item", "qty", "price"],
    query_balance: ["customer"],
    daily_summary: ["day"],
  };
  const REQUIRED = { add_credit: ["customer", "amount"], record_payment: ["customer", "amount"], record_sale: ["item"], update_stock: ["item", "qty"], query_balance: ["customer"], daily_summary: [] };

  function runTool(ledger, name, args) {
    if (!has(TOOL_PARAMS, name)) return { ok: false, action: name, error: `unknown tool ${name}` };
    const clean = {};
    for (const [k, v] of Object.entries(args || {})) if (TOOL_PARAMS[name].includes(k) && v !== null && v !== undefined && v !== "") clean[k] = v;
    const missing = REQUIRED[name].filter((k) => !has(clean, k));
    if (missing.length) return { ok: false, action: name, args: clean, error: `bad arguments: missing ${missing.join(", ")}` };
    try { return ledger[name](clean); } catch (e) {
      if (e instanceof LedgerError) return { ok: false, action: name, args: clean, error: e.message };
      throw e;
    }
  }

  // ------------------------------------------------------------- messages
  const T = {
    add_credit: {
      hi: "{customer} के खाते में {amount} रुपये उधार लिखा। कुल बाकी {balance} रुपये।",
      kn: "{customer} ಅವರ ಖಾತೆಗೆ {amount} ರೂಪಾಯಿ ಸಾಲ ಬರೆದಿದೆ. ಒಟ್ಟು ಬಾಕಿ {balance} ರೂಪಾಯಿ.",
      ta: "{customer} கணக்கில் {amount} ரூபாய் கடன் எழுதப்பட்டது. மொத்த பாக்கி {balance} ரூபாய்.",
      en: "Wrote {amount} rupees credit for {customer}. Total due {balance} rupees.",
    },
    record_payment: {
      hi: "{customer} से {amount} रुपये मिले। अब बाकी {balance} रुपये।",
      kn: "{customer} ಅವರಿಂದ {amount} ರೂಪಾಯಿ ಬಂದಿದೆ. ಈಗ ಬಾಕಿ {balance} ರೂಪಾಯಿ.",
      ta: "{customer} இடமிருந்து {amount} ரூபாய் வந்தது. இப்போது பாக்கி {balance} ரூபாய்.",
      en: "Received {amount} rupees from {customer}. Now due {balance} rupees.",
    },
    payment_advance: {
      hi: "{customer} से {amount} रुपये मिले। उनका {advance} रुपये एडवांस जमा है।",
      kn: "{customer} ಅವರಿಂದ {amount} ರೂಪಾಯಿ ಬಂದಿದೆ. ಅವರ {advance} ರೂಪಾಯಿ ಮುಂಗಡ ಇದೆ.",
      ta: "{customer} இடமிருந்து {amount} ரூபாய் வந்தது. அவர்களுக்கு {advance} ரூபாய் முன்பணம் உள்ளது.",
      en: "Received {amount} rupees from {customer}. They now have {advance} rupees in advance.",
    },
    record_sale: {
      hi: "{qty} {item} की बिक्री दर्ज, {amount} रुपये।",
      kn: "{qty} {item} ಮಾರಾಟ ದಾಖಲಾಗಿದೆ, {amount} ರೂಪಾಯಿ.",
      ta: "{qty} {item} விற்பனை பதிவு, {amount} ரூபாய்.",
      en: "Sale recorded: {qty} {item}, {amount} rupees.",
    },
    record_sale_noprice: {
      hi: "{qty} {item} की बिक्री दर्ज।", kn: "{qty} {item} ಮಾರಾಟ ದಾಖಲಾಗಿದೆ.", ta: "{qty} {item} விற்பனை பதிவு.", en: "Sale recorded: {qty} {item}.",
    },
    credit_sale: {
      hi: "{customer} को {qty} {item} उधार, {amount} रुपये। कुल बाकी {balance} रुपये।",
      kn: "{customer} ಅವರಿಗೆ {qty} {item} ಸಾಲ, {amount} ರೂಪಾಯಿ. ಒಟ್ಟು ಬಾಕಿ {balance} ರೂಪಾಯಿ.",
      ta: "{customer} க்கு {qty} {item} கடன், {amount} ரூபாய். மொத்த பாக்கி {balance} ரூபாய்.",
      en: "{qty} {item} on credit to {customer}, {amount} rupees. Total due {balance} rupees.",
    },
    update_stock: { hi: "{item} का स्टॉक अब {stock}।", kn: "{item} ಸ್ಟಾಕ್ ಈಗ {stock}.", ta: "{item} ஸ்டாக் இப்போது {stock}.", en: "{item} stock is now {stock}." },
    low_stock: {
      hi: "ध्यान दें, {item} सिर्फ {stock} बचे हैं।", kn: "ಗಮನಿಸಿ, {item} ಕೇವಲ {stock} ಉಳಿದಿದೆ.",
      ta: "கவனிக்கவும், {item} {stock} மட்டுமே உள்ளது.", en: "Heads up, only {stock} {item} left.",
    },
    query_balance: {
      hi: "{customer} का कुल बाकी {balance} रुपये है।", kn: "{customer} ಅವರ ಒಟ್ಟು ಬಾಕಿ {balance} ರೂಪಾಯಿ.",
      ta: "{customer} மொத்த பாக்கி {balance} ரூபாய்.", en: "{customer} owes {balance} rupees.",
    },
    query_unknown: {
      hi: "{customer} नाम का कोई खाता नहीं मिला।", kn: "{customer} ಹೆಸರಿನ ಖಾತೆ ಸಿಗಲಿಲ್ಲ.", ta: "{customer} பெயரில் கணக்கு இல்லை.", en: "No account found for {customer}.",
    },
    daily_summary: {
      hi: "आज {sales_count} बिक्री, कुल {sales_total} रुपये। उधार दिया {credit_given}, वसूली {payments_received}। कुल बाकी {outstanding_total} रुपये।",
      kn: "ಇಂದು {sales_count} ಮಾರಾಟ, ಒಟ್ಟು {sales_total} ರೂಪಾಯಿ. ಸಾಲ {credit_given}, ವಸೂಲಿ {payments_received}. ಒಟ್ಟು ಬಾಕಿ {outstanding_total} ರೂಪಾಯಿ.",
      ta: "இன்று {sales_count} விற்பனை, மொத்தம் {sales_total} ரூபாய். கடன் {credit_given}, வசூல் {payments_received}. மொத்த பாக்கி {outstanding_total} ரூபாய்.",
      en: "Today {sales_count} sales, {sales_total} rupees. Credit given {credit_given}, collected {payments_received}. Total outstanding {outstanding_total} rupees.",
    },
    error: { hi: "यह दर्ज नहीं हो पाया: {error}", kn: "ಇದನ್ನು ದಾಖಲಿಸಲು ಆಗಲಿಲ್ಲ: {error}", ta: "இதை பதிவு செய்ய முடியவில்லை: {error}", en: "Could not record that: {error}" },
    not_understood: {
      hi: "माफ़ कीजिए, समझ नहीं आया। फिर से बोलिए।", kn: "ಕ್ಷಮಿಸಿ, ಅರ್ಥವಾಗಲಿಲ್ಲ. ಮತ್ತೊಮ್ಮೆ ಹೇಳಿ.",
      ta: "மன்னிக்கவும், புரியவில்லை. மீண்டும் சொல்லுங்கள்.", en: "Sorry, I didn't catch that. Please say it again.",
    },
  };
  const n = (x) => { if (x === null || x === undefined) return "?"; x = Number(x); return Number.isInteger(x) ? group(x, 0) : group(x, 2); };
  const fill = (tpl, v) => tpl.replace(/\{(\w+)\}/g, (_, k) => (has(v, k) ? String(v[k]) : `{${k}}`));

  function confirm(result, lang) {
    lang = ["hi", "kn", "ta", "en"].includes(lang) ? lang : "hi";
    if (!result.ok) return fill(T.error[lang], { error: result.error || "?" });
    const a = result.action;
    const v = {};
    for (const [k, val] of Object.entries(result)) v[k] = typeof val === "number" ? n(val) : val;
    if (a === "record_sale") {
      const key = result.customer ? "credit_sale" : (result.amount !== null && result.amount !== undefined ? "record_sale" : "record_sale_noprice");
      let text = fill(T[key][lang], v);
      if (result.low_stock && result.stock_left !== null && result.stock_left !== undefined)
        text += " " + fill(T.low_stock[lang], { item: result.item, stock: n(result.stock_left) });
      return text;
    }
    if (a === "update_stock") {
      let text = fill(T.update_stock[lang], v);
      if (result.low_stock) text += " " + fill(T.low_stock[lang], { item: result.item, stock: n(result.stock) });
      return text;
    }
    if (a === "record_payment" && (result.balance || 0) < 0) return fill(T.payment_advance[lang], { ...v, advance: n(-result.balance) });
    if (a === "query_balance" && !result.known) return fill(T.query_unknown[lang], v);
    return fill(T[a][lang], v);
  }
  const notUnderstood = (lang) => (T.not_understood[lang] || T.not_understood.hi);

  // ---------------------------------------------------------------- agent
  class Agent {
    constructor(ledger, opts) { this.ledger = ledger; this.ownerLang = (opts && opts.ownerLang) || "auto"; }
    handleText(transcript, langHint) {
      const t0 = Date.now();
      const snap = this.ledger.snapshot(1);
      const customers = snap.customers.map((c) => c.name);
      const lookup = (q) => { const r = this.ledger.findItem(q); return r ? r.name : null; };
      const plan = parse(transcript, customers, lookup);
      const lang = ["hi", "kn", "ta", "en"].includes(this.ownerLang) ? this.ownerLang : (langHint || plan.lang || detectLang(transcript));
      const results = plan.calls.map((c) => runTool(this.ledger, c.tool, c.args));
      const reply = results.length ? results.map((r) => confirm(r, lang)).join(" ") : notUnderstood(lang);
      return {
        transcript, lang, reply, provider: "rules (in-browser)",
        actions: plan.calls.map((c, i) => ({ tool: c.tool, args: c.args, result: results[i] })),
        ms: Date.now() - t0,
      };
    }
  }

  return { parse, detectLang, ratio, getCloseMatches, Ledger, LedgerError, runTool, confirm, notUnderstood, Agent, REMINDER_TEMPLATES, DEMO_ITEMS };
});

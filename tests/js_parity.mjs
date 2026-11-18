// Parity check for the in-browser demo (docs/js/kirana-core.js) against the Python offline path.
//   1. every sample in samples/utterances.json parses to the expected tool calls and language
//   2. parse() output equals Python rule_parser.parse() for the samples + extra variants
//   3. a full agent run (ledger updates + spoken confirmations) equals the Python agent turn by turn
// Regenerate the Python side with: python scripts/make_js_golden.py
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const K = require("../docs/js/kirana-core.js");
const root = new URL("..", import.meta.url);
const samples = JSON.parse(readFileSync(new URL("samples/utterances.json", root), "utf8"));
const golden = JSON.parse(readFileSync(new URL("tests/fixtures/js_golden.json", root), "utf8"));

let fail = 0, pass = 0;
const eq = (a, b) => JSON.stringify(a) === JSON.stringify(b);
const check = (ok, msg) => { if (ok) pass++; else { fail++; console.error("FAIL", msg); } };
// Python keeps floats (240.0); JSON from Python writes them as 240.0 -> parsed as 240, so plain compare works.
const normCalls = (calls) => calls.map((c) => ({ tool: c.tool, args: Object.fromEntries(Object.entries(c.args).sort()) }));

const fresh = () => { const L = new K.Ledger(null, { shopName: "Sri Lakshmi Kirana" }); L.seedDemo(true); return L; };
const lookupFor = (L) => (q) => { const r = L.findItem(q); return r ? r.name : null; };

// 1. expected actions for the 24 samples (fresh seeded ledger, like the pytest fixture)
{
  const L = fresh();
  const customers = L.snapshot().customers.map((c) => c.name);
  for (const s of samples) {
    const r = K.parse(s.text, customers, lookupFor(L));
    const ok = r.calls.length === s.expected.length && r.lang === s.lang &&
      r.calls.every((c, i) => c.tool === s.expected[i].tool && Object.entries(s.expected[i].args).every(([k, v]) => c.args[k] === v));
    check(ok, `sample ${s.id}: ${JSON.stringify(r)}`);
  }
  console.log(`samples: ${samples.length} checked`);
}

// 2. parser parity with Python
{
  const L = fresh();
  check(eq(L.snapshot().customers.map((c) => c.name), golden.seed_customers), "seed customer order");
  for (const g of golden.parses) {
    const r = K.parse(g.text, golden.seed_customers, lookupFor(L));
    check(r.lang === g.lang && eq(normCalls(r.calls), normCalls(g.calls)), `parse "${g.text}": js=${JSON.stringify(r)} py=${JSON.stringify(g)}`);
  }
  console.log(`parser parity: ${golden.parses.length} utterances`);
}

// 3. full agent parity (sequential, state carries over)
{
  const L = fresh();
  const ag = new K.Agent(L);
  for (const g of golden.run) {
    const out = ag.handleText(g.text, "");
    const acts = out.actions.map((a) => ({ tool: a.tool, args: a.args, ok: a.result.ok }));
    check(out.lang === g.lang && out.reply === g.reply && eq(normCalls(acts), normCalls(g.actions)) && eq(acts.map((a) => a.ok), g.actions.map((a) => a.ok)),
      `agent "${g.text}":\n  js=${out.reply}\n  py=${g.reply}`);
  }
  const snap = L.snapshot(200);
  const final = {
    customers: Object.fromEntries(snap.customers.map((c) => [c.name, c.balance])),
    items: Object.fromEntries(snap.items.map((i) => [i.name, i.stock])),
    sales: snap.sales.length,
  };
  check(eq(final, golden.final), `final state js=${JSON.stringify(final)} py=${JSON.stringify(golden.final)}`);
  // customer order (balance desc) must match too
  check(eq(Object.keys(final.customers), Object.keys(golden.final.customers)), "customer order");
  console.log(`agent parity: ${golden.run.length} turns + final ledger state`);
}

// 4. localStorage-style round trip keeps working
{
  const L = fresh(); L.add_credit({ customer: "Ramesh", amount: 10 });
  const L2 = new K.Ledger(JSON.parse(JSON.stringify(L.toJSON())));
  check(L2.query_balance({ customer: "Ramesh" }).balance === 10, "state round trip");
  check(L2.reminders("hi")[0].whatsapp_url.startsWith("https://wa.me/?text="), "reminder link");
}

// 5. the demo page's copy of the samples is in sync
{
  const site = readFileSync(new URL("docs/data/utterances.json", root), "utf8");
  check(eq(JSON.parse(site), samples), "docs/data/utterances.json is out of sync with samples/utterances.json (cp it)");
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);

// Runs frontend/tciot-icons.js in Node with a file-backed fetch and prints a
// JSON report that tests/test_frontend_module.py asserts on.
// Usage: node iconset_harness.mjs <path to tciot-icons.js>
import { readFile } from "node:fs/promises";
import { pathToFileURL, fileURLToPath } from "node:url";

const moduleUrl = pathToFileURL(process.argv[2]);
moduleUrl.searchParams.set("v", "9.9.9");

const requests = [];
let failNext = 0;

globalThis.window = { customIcons: { other: { marker: true } } };
globalThis.fetch = async (input) => {
  const url = new URL(String(input));
  requests.push(url.href);
  if (failNext > 0) {
    failNext -= 1;
    return { ok: false, status: 503, json: async () => ({}) };
  }
  const plain = new URL(url.href);
  plain.search = "";
  try {
    const text = await readFile(fileURLToPath(plain), "utf-8");
    return { ok: true, status: 200, json: async () => JSON.parse(text) };
  } catch {
    return { ok: false, status: 404, json: async () => ({}) };
  }
};
const warnings = [];
console.warn = (...args) => warnings.push(args.map(String).join(" "));

await import(moduleUrl.href);

const set = window.customIcons.tciot;
const report = { otherKept: window.customIcons.other?.marker === true };
report.api = [typeof set?.getIcon, typeof set?.getIconList];
const count = (suffix) =>
  requests.filter((r) => new URL(r).pathname.endsWith(suffix)).length;

// A failed chunk load gives an empty icon, warns and is retried next time.
failNext = 1;
report.failed = await set.getIcon("water_drop");
report.warnedOnFailure = warnings.length;
report.retried = await set.getIcon("water_drop");
report.wRequests = count("/w.json");

// Cache: concurrent and repeated requests load a chunk once.
const [a, b] = await Promise.all([
  set.getIcon("heat_pump"),
  set.getIcon("home"),
]);
report.heatPump = a;
report.home = b;
report.normalized = await set.getIcon("  Heat-Pump ");
report.spaced = await set.getIcon("heat pump");
report.hRequests = count("/h.json");

report.digit = await set.getIcon("10k");
report.digitRequests = count("/0.json");
report.unknown = await set.getIcon("not_a_symbol");
report.empty = await set.getIcon("");
report.notAString = await set.getIcon(undefined);

const list1 = await set.getIconList();
const list2 = await set.getIconList();
report.listLength = list1.length;
report.listSample = list1.slice(0, 3);
report.listShapeOk = list2.every(
  (e) => typeof e.name === "string" && e.name.length > 0,
);
report.namesRequests = count("/names.json");

report.allVersioned = requests.every(
  (r) => new URL(r).searchParams.get("v") === "9.9.9",
);
report.allBelowModule = requests.every((r) =>
  r.startsWith(new URL("material_symbols/", moduleUrl).href),
);
report.warnings = warnings.length;

process.stdout.write(JSON.stringify(report));

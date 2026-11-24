// Custom icon set "tciot" for the Home Assistant frontend: the original
// Google Material Symbols (outlined, weight 400; Apache-2.0, see
// material_symbols/LICENSE). Usage: icon "tciot:heat_pump".
//
// The symbol paths are split into one JSON file per first character and are
// loaded on demand from Home Assistant itself, so the frontend only downloads
// what it shows and no internet access is needed.
(() => {
  const PREFIX = "tciot";
  const DEFAULT_VIEWBOX = "0 -960 960 960";
  const moduleUrl = new URL(import.meta.url);
  const version = moduleUrl.searchParams.get("v") || "0";
  const base = new URL("material_symbols/", moduleUrl);

  const chunks = new Map();
  let names;

  const fileUrl = (file) => {
    const url = new URL(file, base);
    url.searchParams.set("v", version);
    return url;
  };

  const loadJson = async (file) => {
    const response = await fetch(fileUrl(file));
    if (!response.ok) {
      throw new Error(`${PREFIX}: ${file} HTTP ${response.status}`);
    }
    return response.json();
  };

  const normalize = (name) =>
    String(name).trim().toLowerCase().replace(/[-\s]/g, "_");

  const chunkFor = (name) => {
    const first = name.charAt(0);
    const key = first >= "a" && first <= "z" ? first : "0";
    if (!chunks.has(key)) {
      // Forget a failed load so the next icon request retries it.
      const pending = loadJson(`${key}.json`).catch((err) => {
        chunks.delete(key);
        throw err;
      });
      chunks.set(key, pending);
    }
    return chunks.get(key);
  };

  const getIcon = async (name) => {
    const symbol = normalize(name);
    let entry;
    try {
      entry = (await chunkFor(symbol))[symbol];
    } catch (err) {
      console.warn(err);
    }
    if (entry === undefined) {
      return { path: "" };
    }
    return Array.isArray(entry)
      ? { path: entry[0], viewBox: entry[1] }
      : { path: entry, viewBox: DEFAULT_VIEWBOX };
  };

  const getIconList = async () => {
    if (!names) {
      names = loadJson("names.json").catch((err) => {
        names = undefined;
        throw err;
      });
    }
    return (await names).map((name) => ({ name }));
  };

  window.customIcons = window.customIcons || {};
  window.customIcons[PREFIX] = { getIcon, getIconList };
})();

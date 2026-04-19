import { defineConfig } from "astro/config";
import path from "node:path";
import { fileURLToPath } from "node:url";

// Update `site` to match your GitHub Pages URL. For a user/org site served at
// the repo root, leave `base` as "/". For a project site at
// https://<user>.github.io/read-the-syspapers, set base to "/read-the-syspapers".
const BASE = "/read-the-syspapers";
const CONTENT_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "src/content");

// Markdown content (blog posts, conference overviews, paper summaries) links to
// sibling pages in two shapes:
//   1. Relative markdown-file paths like `../papers/<conf>/<slug>.md` — the
//      canonical project convention. Astro does not rewrite these, so we resolve
//      them against the source file's location under `src/content/` and map to
//      the corresponding site route `<BASE>/<lang>/<...>`, using the source
//      file's own `.<lang>.md` suffix so English and Chinese twins both land on
//      language-matched pages without per-link rewriting.
//   2. Root-absolute paths like `/<lang>/papers/<conf>/<slug>` — older-style
//      citations. Astro does not auto-apply `base` to these at render time, so
//      we prefix `BASE` when missing.
// Hand-rolled tree walk keeps us off new dependencies.
function rehypeLinkRewrite() {
  const prefix = BASE.replace(/\/$/, "");
  return (tree, file) => {
    const src = (file && (file.path || (file.history && file.history[0]))) || "";
    const langMatch = src.match(/\.(en|zh-cn)\.md$/);
    const sourceLang = langMatch ? langMatch[1] : "en";
    const sourceDir = src ? path.dirname(src) : "";

    const rewrite = (v) => {
      if (typeof v !== "string" || v.length === 0) return null;
      if (v.startsWith("#") || v.startsWith("//") || /^[a-z][a-z0-9+.-]*:/i.test(v)) return null;

      // Relative .md content link → resolve against source file, map to route.
      if (!v.startsWith("/") && /\.md(?=$|[#?])/.test(v) && sourceDir) {
        const splitIdx = v.search(/[#?]/);
        const linkPath = splitIdx === -1 ? v : v.slice(0, splitIdx);
        const suffix = splitIdx === -1 ? "" : v.slice(splitIdx);
        const absLinkPath = path.resolve(sourceDir, linkPath);
        const relFromContent = path.relative(CONTENT_ROOT, absLinkPath);
        if (relFromContent && !relFromContent.startsWith("..") && !path.isAbsolute(relFromContent)) {
          const stripped = relFromContent
            .replace(/\.(en|zh-cn)\.md$/, "")
            .replace(/\.md$/, "");
          const urlPath = stripped.split(path.sep).join("/");
          return `${prefix}/${sourceLang}/${urlPath}${suffix}`;
        }
      }

      // Root-absolute path → add base prefix if missing.
      if (
        v.startsWith("/") &&
        !v.startsWith(prefix + "/") &&
        v !== prefix
      ) {
        return prefix + v;
      }

      return null;
    };

    const walk = (node) => {
      if (node && node.type === "element" && node.properties) {
        if (node.tagName === "a" || node.tagName === "img") {
          const attr = node.tagName === "a" ? "href" : "src";
          const next = rewrite(node.properties[attr]);
          if (next !== null) node.properties[attr] = next;
        }
      }
      if (node && Array.isArray(node.children)) {
        for (const child of node.children) walk(child);
      }
    };
    walk(tree);
  };
}

export default defineConfig({
  site: "https://tth37.github.io",
  base: BASE,
  trailingSlash: "ignore",
  build: {
    format: "directory",
  },
  markdown: {
    rehypePlugins: [rehypeLinkRewrite],
  },
});

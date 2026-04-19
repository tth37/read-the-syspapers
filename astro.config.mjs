import { defineConfig } from "astro/config";

// Update `site` to match your GitHub Pages URL. For a user/org site served at
// the repo root, leave `base` as "/". For a project site at
// https://<user>.github.io/read-the-syspapers, set base to "/read-the-syspapers".
const BASE = "/read-the-syspapers";

// Markdown content (blog posts, conference overviews, paper summaries) routinely
// links to other pages via root-absolute paths like `/en/papers/<conf>/<slug>`.
// Astro does not auto-prefix `base` into those at render time, so in production
// they resolve to `https://tth37.github.io/en/papers/...` and 404. This rehype
// pass rewrites every anchor/image whose href or src is root-absolute (starts
// with a single `/`, not `//…`, not already prefixed) to include the base.
// Hand-rolled tree walk keeps us off new dependencies.
function rehypeBasePrefix() {
  const prefix = BASE.replace(/\/$/, "");
  return (tree) => {
    const walk = (node) => {
      if (node && node.type === "element" && node.properties) {
        if (node.tagName === "a" || node.tagName === "img") {
          const attr = node.tagName === "a" ? "href" : "src";
          const v = node.properties[attr];
          if (
            typeof v === "string" &&
            v.startsWith("/") &&
            !v.startsWith("//") &&
            !v.startsWith(prefix + "/") &&
            v !== prefix
          ) {
            node.properties[attr] = prefix + v;
          }
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
    rehypePlugins: [rehypeBasePrefix],
  },
});

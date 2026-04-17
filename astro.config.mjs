import { defineConfig } from "astro/config";

// Update `site` to match your GitHub Pages URL. For a user/org site served at
// the repo root, leave `base` as "/". For a project site at
// https://<user>.github.io/read-the-syspapers, set base to "/read-the-syspapers".
export default defineConfig({
  site: "https://example.github.io",
  base: "/read-the-syspapers",
  trailingSlash: "ignore",
  build: {
    format: "directory",
  },
});

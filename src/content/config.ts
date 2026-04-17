import { defineCollection, z } from "astro:content";
import { glob } from "astro/loaders";

// Venues. Extend this list as you add new conferences — the site UI groups by venue.
const VENUES = [
  "OSDI",
  "SOSP",
  "NSDI",
  "ATC",
  "EuroSys",
  "ASPLOS",
  "FAST",
  "MLSys",
  "SIGCOMM",
  "VLDB",
  "SIGMOD",
  "USENIX-Security",
  "CCS",
  "S&P",
  "NDSS",
  "HPCA",
  "ISCA",
  "MICRO",
  "PLDI",
  "POPL",
  "SC",
  "PPoPP",
  "HotOS",
] as const;

export const LANGS = ["en", "zh-cn"] as const;
export type Lang = (typeof LANGS)[number];

const WRITTEN_BY_EXAMPLES = [
  "claude-code",
  "codex",
  "cursor",
  "gemini",
  "aider",
  "windsurf",
  "human",
];

// One category = one session/track within a conference. Each conference file (per
// language) declares its own categories array. Paper.category references the id.
const categorySchema = z.object({
  id: z.string().regex(/^[a-z0-9][a-z0-9-]*$/, "category id must be kebab-case"),
  title: z.string(),
  description: z.string().optional(),
});

// Preserve the `.en` / `.zh-cn` language suffix on the id (Astro's default generateId
// slugifies it away). e.g. `osdi-2025.en.md` → id `osdi-2025.en`; `osdi-2025/foo.zh-cn.md`
// → id `osdi-2025/foo.zh-cn`.
const keepDotsId = ({ entry }: { entry: string }) => entry.replace(/\.md$/, "");

const conferences = defineCollection({
  loader: glob({ pattern: "**/*.md", base: "./src/content/conferences", generateId: keepDotsId }),
  schema: z.object({
    venue: z.enum(VENUES),
    year: z.number().int().min(1990).max(2100),
    title: z.string(),
    location: z.string().optional(),
    dates: z.string().optional(),
    url: z.string().url(),
    paper_count_expected: z.number().int().nonnegative().optional(),
    overview_status: z.enum(["pending", "in-progress", "complete"]).default("pending"),
    // Agent id ("claude-code", "codex", …). null until populated.
    written_by: z.string().nullable().default(null),
    summary_date: z.coerce.date().nullable().default(null),
    // Ordered list of categories/tracks for this conference. Order drives both the ToC
    // and the section order on the page. Papers whose `category` is not in this list are
    // rendered last under "Other".
    categories: z.array(categorySchema).default([]),
  }),
});

const papers = defineCollection({
  loader: glob({ pattern: "**/*.md", base: "./src/content/papers", generateId: keepDotsId }),
  schema: z.object({
    title: z.string(),
    // One-line TL;DR shown on the conference page and paper cards. Language-specific.
    oneline: z.string().min(1).max(400),
    authors: z.array(z.string()).min(1),
    affiliations: z.array(z.string()).default([]),
    // Base slug of the conference, e.g. "asplos-2026" (no .en / .zh-cn suffix).
    conference: z.string().regex(/^[a-z0-9][a-z0-9-]*$/, "base slug only, no language suffix"),
    // Category id, must match one of the conference's `categories[].id`. Optional —
    // "uncategorized" papers are grouped at the end.
    category: z.string().regex(/^[a-z0-9][a-z0-9-]*$/).optional(),
    pdf_url: z.string().url().optional(),
    doi_url: z.string().url().optional(),
    code_url: z.string().url().optional(),
    project_url: z.string().url().optional(),
    tags: z.array(z.string()).default([]),
    reading_status: z.enum(["unread", "skimmed", "read"]).default("unread"),
    star: z.boolean().default(false),
    // Agent id. Examples: claude-code, codex, cursor, gemini, aider, human.
    written_by: z.string(),
    summary_date: z.coerce.date(),
  }),
});

export const collections = { conferences, papers };

export { VENUES, WRITTEN_BY_EXAMPLES };

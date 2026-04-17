import { defineCollection, reference, z } from "astro:content";
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

const WRITTEN_BY_EXAMPLES = [
  "claude-code",
  "codex",
  "cursor",
  "gemini",
  "aider",
  "windsurf",
  "human",
];

const conferences = defineCollection({
  loader: glob({ pattern: "**/*.md", base: "./src/content/conferences" }),
  schema: z.object({
    venue: z.enum(VENUES),
    year: z.number().int().min(1990).max(2100),
    title: z.string(),
    location: z.string().optional(),
    dates: z.string().optional(),
    url: z.string().url(),
    paper_count_expected: z.number().int().nonnegative().optional(),
    overview_status: z.enum(["pending", "in-progress", "complete"]).default("pending"),
    // Agent id (e.g. "claude-code", "codex"). null until populated.
    written_by: z.string().nullable().default(null),
    summary_date: z.coerce.date().nullable().default(null),
  }),
});

const papers = defineCollection({
  loader: glob({ pattern: "**/*.md", base: "./src/content/papers" }),
  schema: z.object({
    title: z.string(),
    authors: z.array(z.string()).min(1),
    affiliations: z.array(z.string()).default([]),
    conference: reference("conferences"),
    pdf_url: z.string().url().optional(),
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

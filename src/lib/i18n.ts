import type { Lang } from "./paths";

type StringKeys =
  | "nav.conferences"
  | "nav.tags"
  | "nav.search"
  | "home.tagline"
  | "home.recent"
  | "home.brand"
  | "home.featured"
  | "home.featured.sub"
  | "home.shuffle"
  | "home.venues"
  | "home.venues.sub"
  | "home.stat.papers"
  | "home.stat.venues"
  | "home.stat.years"
  | "home.venue.papers_one"
  | "home.venue.papers_other"
  | "conferences.all"
  | "conferences.all.subtitle"
  | "conferences.official_site"
  | "conferences.papers_summarized"
  | "conferences.toc"
  | "conferences.uncategorized"
  | "conferences.overview_pending"
  | "conferences.no_papers"
  | "card.awaiting_summary"
  | "card.in_progress"
  | "card.overview_complete"
  | "card.papers_count_one"
  | "card.papers_count_other"
  | "paper.pdf"
  | "paper.code"
  | "paper.project"
  | "paper.doi"
  | "paper.written_by_prefix"
  | "paper.not_yet_summarized"
  | "tags.title"
  | "tags.none_yet"
  | "tags.n_papers_one"
  | "tags.n_papers_other"
  | "search.title"
  | "search.hint"
  | "search.not_built"
  | "footer.blurb"
  | "lang.switch_label";

export const UI: Record<Lang, Record<StringKeys, string>> = {
  en: {
    "nav.conferences": "Conferences",
    "nav.tags": "Tags",
    "nav.search": "Search",
    "home.brand": "read-the-syspapers",
    "home.tagline":
      "Long-form summaries of papers from systems top conferences — OSDI, SOSP, NSDI, ATC, EuroSys, ASPLOS, FAST, MLSys, and more. Each summary is produced by a coding agent (Claude Code, Codex, …) following a shared template, and records which agent wrote it.",
    "home.recent": "Recently summarized",
    "home.featured": "Featured picks",
    "home.featured.sub": "A handful of papers, freshly shuffled.",
    "home.shuffle": "shuffle",
    "home.venues": "Venues",
    "home.venues.sub": "Browse all conferences by venue.",
    "home.stat.papers": "papers",
    "home.stat.venues": "venues",
    "home.stat.years": "years",
    "home.venue.papers_one": "{n} paper",
    "home.venue.papers_other": "{n} papers",
    "conferences.all": "Conferences",
    "conferences.all.subtitle": "All venues, most recent first.",
    "conferences.official_site": "official site",
    "conferences.papers_summarized": "papers summarized",
    "conferences.toc": "Categories",
    "conferences.uncategorized": "Other",
    "conferences.overview_pending": "No overview yet. Run the agent harness (see prompts/conference-overview.md).",
    "conferences.no_papers": "No summaries yet. Run the agent harness: see prompts/conference-overview.md.",
    "card.awaiting_summary": "awaiting summary",
    "card.in_progress": "in progress",
    "card.overview_complete": "overview complete",
    "card.papers_count_one": "{n} paper summarized",
    "card.papers_count_other": "{n} papers summarized",
    "paper.pdf": "PDF",
    "paper.code": "code",
    "paper.project": "project",
    "paper.doi": "DOI",
    "paper.written_by_prefix": "written by:",
    "paper.not_yet_summarized": "not yet summarized",
    "tags.title": "Tags",
    "tags.none_yet": "No tags yet — summaries haven't been generated.",
    "tags.n_papers_one": "{n} paper tagged",
    "tags.n_papers_other": "{n} papers tagged",
    "search.title": "Search",
    "search.hint": "Full-text across conference overviews and paper summaries. Built with Pagefind.",
    "search.not_built": "Search index not built yet. Run npm run build locally.",
    "footer.blurb": "read-the-syspapers · built with Astro",
    "lang.switch_label": "Language",
  },
  "zh-cn": {
    "nav.conferences": "会议",
    "nav.tags": "标签",
    "nav.search": "搜索",
    "home.brand": "read-the-syspapers",
    "home.tagline":
      "系统方向顶级会议（OSDI、SOSP、NSDI、ATC、EuroSys、ASPLOS、FAST、MLSys 等）论文的深度综述。每篇综述均由编程智能体（Claude Code、Codex 等）按统一模板撰写，并记录由哪个智能体完成。",
    "home.recent": "最近整理",
    "home.featured": "精选推荐",
    "home.featured.sub": "随机抽取的几篇论文。",
    "home.shuffle": "换一批",
    "home.venues": "会议列表",
    "home.venues.sub": "按会议浏览全部收录。",
    "home.stat.papers": "篇论文",
    "home.stat.venues": "个会议",
    "home.stat.years": "年",
    "home.venue.papers_one": "{n} 篇",
    "home.venue.papers_other": "{n} 篇",
    "conferences.all": "会议",
    "conferences.all.subtitle": "全部会议，按时间倒序排列。",
    "conferences.official_site": "官方网站",
    "conferences.papers_summarized": "篇论文已综述",
    "conferences.toc": "分类",
    "conferences.uncategorized": "其他",
    "conferences.overview_pending": "尚未生成综述。请运行 prompts/conference-overview.md 中的智能体流程。",
    "conferences.no_papers": "尚无综述。请运行 prompts/conference-overview.md 中的智能体流程。",
    "card.awaiting_summary": "待生成",
    "card.in_progress": "进行中",
    "card.overview_complete": "综述完成",
    "card.papers_count_one": "已综述 {n} 篇",
    "card.papers_count_other": "已综述 {n} 篇",
    "paper.pdf": "PDF",
    "paper.code": "代码",
    "paper.project": "项目主页",
    "paper.doi": "DOI",
    "paper.written_by_prefix": "撰写者：",
    "paper.not_yet_summarized": "尚未综述",
    "tags.title": "标签",
    "tags.none_yet": "暂无标签 —— 综述尚未生成。",
    "tags.n_papers_one": "共 {n} 篇论文标记为",
    "tags.n_papers_other": "共 {n} 篇论文标记为",
    "search.title": "搜索",
    "search.hint": "全文检索会议综述与论文摘要，由 Pagefind 构建。",
    "search.not_built": "搜索索引尚未构建。请在本地执行 npm run build。",
    "footer.blurb": "read-the-syspapers · built with Astro",
    "lang.switch_label": "语言",
  },
};

export function t(lang: Lang, key: StringKeys, vars?: Record<string, string | number>): string {
  let s = UI[lang][key] ?? UI.en[key] ?? key;
  if (vars) for (const k of Object.keys(vars)) s = s.replaceAll(`{${k}}`, String(vars[k]));
  return s;
}

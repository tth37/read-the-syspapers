import { LANGS, type Lang } from "../content/config";

const BASE = import.meta.env.BASE_URL.replace(/\/$/, "");

export { LANGS };
export type { Lang };

export const DEFAULT_LANG: Lang = "en";

export const LANG_LABELS: Record<Lang, string> = {
  en: "English",
  "zh-cn": "简体中文",
};

export function isLang(value: string): value is Lang {
  return (LANGS as readonly string[]).includes(value);
}

// Content-collection ids are `<base-slug>.<lang>`. Split them.
export function splitLangId(id: string): { base: string; lang: Lang } {
  for (const l of LANGS) {
    const suffix = `.${l}`;
    if (id.endsWith(suffix)) return { base: id.slice(0, -suffix.length), lang: l };
  }
  return { base: id, lang: DEFAULT_LANG };
}

export function baseSlug(id: string): string {
  return splitLangId(id).base;
}

export function idLang(id: string): Lang {
  return splitLangId(id).lang;
}

// For papers, ids are `<conference>/<slug>.<lang>` because files live in conference
// subdirectories. This extracts just the paper slug.
export function paperParts(id: string): { conference: string; slug: string; lang: Lang } {
  const { base, lang } = splitLangId(id);
  const parts = base.split("/");
  const slug = parts[parts.length - 1];
  const conference = parts.slice(0, -1).join("/");
  return { conference, slug, lang };
}

export function url(lang: Lang, path: string): string {
  const clean = path.startsWith("/") ? path : `/${path}`;
  return `${BASE}/${lang}${clean}`;
}

export function homeHref(lang: Lang): string {
  return url(lang, "/");
}

export function conferencesHref(lang: Lang): string {
  return url(lang, "/conferences");
}

export function conferenceHref(lang: Lang, id: string): string {
  return url(lang, `/conferences/${id}`);
}

export function paperHref(lang: Lang, conferenceId: string, paperSlug: string): string {
  return url(lang, `/papers/${conferenceId}/${paperSlug}`);
}

export function tagsHref(lang: Lang): string {
  return url(lang, "/tags");
}

export function tagHref(lang: Lang, tag: string): string {
  return url(lang, `/tags/${encodeURIComponent(tag)}`);
}

export function searchHref(lang: Lang): string {
  return url(lang, "/search");
}

export function blogHref(lang: Lang): string {
  return url(lang, "/blog");
}

export function blogPostHref(lang: Lang, slug: string): string {
  return url(lang, `/blog/${slug}`);
}

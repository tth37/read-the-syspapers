const BASE = import.meta.env.BASE_URL.replace(/\/$/, "");

export function url(path: string): string {
  const clean = path.startsWith("/") ? path : `/${path}`;
  return `${BASE}${clean}`;
}

export function conferenceHref(id: string): string {
  return url(`/conferences/${id}`);
}

export function paperHref(conferenceId: string, paperSlug: string): string {
  return url(`/papers/${conferenceId}/${paperSlug}`);
}

export function tagHref(tag: string): string {
  return url(`/tags/${encodeURIComponent(tag)}`);
}

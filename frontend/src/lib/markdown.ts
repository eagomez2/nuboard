import DOMPurify from 'dompurify';
import { Marked } from 'marked';

const escape = (s: string) =>
  s.replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]!);

// Base URL of report-local files (`files/...`), set for the duration of one render
let base = '';

const marked = new Marked({
  gfm: true,
  breaks: false,
  renderer: {
    image({ href, title, text }) {
      // `![caption](media:<run>/<key>@<step>)` becomes a placeholder the viewer fills in
      if (href.startsWith('media:'))
        return `<span class="nb-embed" data-ref="${escape(href.slice(6))}" data-caption="${escape(text)}"></span>`;
      // Outside images are never loaded: that would tell their host who reads the report, and
      // break offline. They show as a link instead.
      if (/^([a-z][a-z0-9+.-]*:)?\/\//i.test(href) && !href.startsWith('data:'))
        return `<a href="${escape(href)}" class="nb-external" title="Outside image, not loaded">${escape(text || href)}</a>`;
      const src = base && href.startsWith('files/') ? base + href : href;
      // `![caption](files/x.png "chart:<spec>")`: a chart snapshot the viewer draws live
      if (title?.startsWith('chart:'))
        return `<span class="nb-chart" data-spec="${escape(title.slice(6))}" data-caption="${escape(text)}" data-src="${escape(src)}"></span>`;
      // `![caption](files/x.png "overlay:<ref> <ref> ...")`: every run's PR curve or distribution, drawn live
      if (title?.startsWith('overlay:'))
        return `<span class="nb-overlay" data-refs="${escape(title.slice(8))}" data-caption="${escape(text)}" data-src="${escape(src)}"></span>`;
      // `![caption](files/x.png "view:<page>?<params>")`: a snapshot linked to the page it came from
      if (title?.startsWith('view:'))
        return `<span class="nb-view" data-view="${escape(title.slice(5))}" data-caption="${escape(text)}" data-src="${escape(src)}"></span>`;
      if (src !== href) return `<img src="${escape(src)}" alt="${escape(text)}">`;
      return false;
    },
    link({ href, title, tokens, text }) {
      if (!href.startsWith('files/')) return false;
      const src = base ? base + href : href;
      // `[train.log](files/x.log "attachment")`: an attached file, shown as a collapsible block
      if (title === 'attachment')
        return `<span class="nb-attach" data-src="${escape(src)}" data-name="${escape(text)}"></span>`;
      return `<a href="${escape(src)}">${this.parser.parseInline(tokens)}</a>`;
    },
  },
});

/**
 * Render Markdown to sanitized HTML; links open in a new tab.
 *
 * `files` is the URL prefix of report-local files such as chart snapshots.
 */
export function renderMarkdown(text: string, files = ''): string {
  base = files;
  try {
    const html = marked.parse(text, { async: false }) as string;
    return DOMPurify.sanitize(html, {
      ADD_ATTR: ['data-ref', 'data-refs', 'data-caption', 'data-spec', 'data-src', 'data-view', 'data-name', 'target'],
    });
  } finally {
    base = '';
  }
}

DOMPurify.addHook('afterSanitizeAttributes', (node) => {
  if (node.tagName === 'A' && node.getAttribute('href')?.match(/^https?:/)) {
    node.setAttribute('target', '_blank');
    node.setAttribute('rel', 'noopener noreferrer');
  }
});

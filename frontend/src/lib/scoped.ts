import type { Page } from './router.svelte';

/**
 * Pages that can be limited to runs picked on the Runs page (`sel` in the URL), in the order of the nav rail.
 * The Runs selection bar, the run details ⋮ menu and the "Showing N selected runs" banner all offer these.
 */
export const SCOPED_PAGES: readonly { page: Page; label: string; icon: string }[] = [
  { page: 'charts', label: 'Charts', icon: 'charts' },
  { page: 'media', label: 'Media', icon: 'media' },
  { page: 'sweeps', label: 'Sweeps', icon: 'sweep' },
  { page: 'select', label: 'Shortlist', icon: 'flag' },
  { page: 'timeline', label: 'Timeline', icon: 'timeline' },
];

export const isScoped = (page: Page) => SCOPED_PAGES.some((p) => p.page === page);

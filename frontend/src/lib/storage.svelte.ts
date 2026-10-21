// Whether the Storage window is open, and on which tab; opened from the rail and the Artifacts page.
export const storageView = $state<{ open: boolean; tab: 'runs' | 'artifacts' }>({ open: false, tab: 'runs' });

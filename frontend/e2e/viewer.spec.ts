import { expect, test } from '@playwright/test';

test('runs table lists the demo projects and filters with the query bar', async ({ page }) => {
  await page.goto('/#/runs');
  await expect(page.getByRole('button', { name: /llm-pretrain/ })).toBeVisible();
  await expect(page.getByText('crashed').first()).toBeVisible();
  const query = page.getByLabel('Run query');
  await query.fill('where status = crashed');
  await query.press('Enter');
  await expect(page.locator('.body .row')).toHaveCount(1);
  await expect(page).toHaveURL(/q=where/);
});

test('compare two runs shows a config diff', async ({ page }) => {
  await page.goto('/#/runs?project=vit-ablations');
  const boxes = page.locator('.body .row input[type=checkbox]');
  await boxes.nth(0).check();
  await boxes.nth(2).check();
  await page.getByRole('button', { name: 'Compare' }).click();
  await page.getByRole('button', { name: 'config.yaml' }).click();
  await expect(page.locator('.line.del').first()).toBeVisible();
});

test('compare opens on screen and takes more than two runs', async ({ page }) => {
  await page.goto('/#/runs?project=llm-pretrain');
  const boxes = page.locator('.body .row input[type=checkbox]');
  for (const i of [0, 1, 2, 3]) await boxes.nth(i).check();
  await page.getByRole('button', { name: 'Compare' }).click();
  await expect(page.getByRole('heading', { name: /Compare 4 runs/ })).toBeInViewport();
  await expect(page.locator('.srow.head .run')).toHaveCount(4);
  await page.getByRole('button', { name: 'config.yaml' }).click();
  await page.getByRole('combobox', { name: 'Right run' }).selectOption({ index: 3 });
  await expect(page).toHaveURL(/pair=0(,|%2C)3/);
});

test('charts render grouped bands, a legend and small multiples', async ({ page }) => {
  await page.goto('/#/charts?q=where%20tags%20has%20sweep%20group%20by%20config.optim.lr');
  await expect(page.locator('.legend-chip')).toHaveCount(4);
  await expect(page.locator('.main canvas')).toBeVisible();
  await page.locator('.small').first().scrollIntoViewIfNeeded(); // small charts load on scroll
  await expect(page.locator('.small canvas').first()).toBeVisible();
  await page.getByRole('button', { name: 'wall time' }).click();
  await expect(page).toHaveURL(/x=time/);
});

test('media page shows logged images', async ({ page }) => {
  await page.goto('/#/media?project=vit-ablations&mfind=%5Esamples%2Faugmented%24');
  await expect(page.locator('figure img').first()).toBeVisible();
  await expect(page.getByText(/^1 of \d+$/)).toBeVisible();
  await page.getByLabel('Filter keys').fill('^nothing-here$');
  await expect(page.getByText('No key matches')).toBeVisible();
});

test('runs table shows alerts, collections and editable custom fields', async ({ page }) => {
  await page.goto('/#/runs?project=llm-pretrain&cols=field:verdict');
  await expect(page.getByRole('button', { name: /health alert/ }).first()).toBeVisible();
  await page
    .getByRole('button', { name: /shortlist/ })
    .first()
    .click();
  await expect(page).toHaveURL(/q=collections\+has/);
  await expect(page.locator('.body .row')).toHaveCount(3);
  const cell = page.locator('.body .row').first().locator('.fieldcell button');
  await cell.click();
  const input = page.locator('.fieldcell input');
  await input.fill('e2e-checked');
  await input.press('Enter');
  await page.getByLabel('Run query').fill('verdict = e2e-checked');
  await page.getByLabel('Run query').press('Enter');
  await expect(page.locator('.body .row')).toHaveCount(1);
});

test('sweeps page draws parallel coordinates and filters by brushing', async ({ page }) => {
  await page.goto('/#/sweeps?project=llm-pretrain&metric=train%2Floss&params=optim.lr');
  await expect(page.locator('.pc .axis')).toHaveCount(2);
  const before = await page.locator('.pc path.line:not(.dim)').count();
  expect(before).toBeGreaterThan(10);
  const hit = page.locator('.pc .hit').first();
  const box = (await hit.boundingBox())!;
  await page.mouse.move(box.x + box.width / 2, box.y + 10);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width / 2, box.y + box.height * 0.3, { steps: 5 });
  await page.mouse.up();
  await expect(page.locator('.pc path.line.dim').first()).toBeAttached();
  expect(await page.locator('.pc path.line:not(.dim)').count()).toBeLessThan(before);
});

test('timeline shows a bar per run and artifacts show lineage', async ({ page }) => {
  await page.goto('/#/timeline?project=llm-pretrain');
  await expect(page.locator('g.bar').first()).toBeVisible();
  expect(await page.locator('g.bar').count()).toBeGreaterThan(12);
  await page.goto('/#/artifacts?project=llm-pretrain');
  await expect(page.getByRole('heading', { name: 'fineweb-edu:v2' })).toBeVisible();
  await expect(page.locator('g.node.run')).toHaveCount(14);
  await page.locator('g.node.artifact', { hasText: 'model:v1' }).click();
  await expect(page.getByRole('heading', { name: 'model:v1' })).toBeVisible();
});

test('charts can use another metric as the x axis', async ({ page }) => {
  await page.goto('/#/charts?project=llm-pretrain');
  await page.locator('select.xmetric').selectOption('train/tokens');
  await expect(page).toHaveURL(/x=metric(:|%3A)train(\/|%2F)tokens/);
  await expect(page.locator('select.xmetric')).toHaveClass(/\bon\b/);
  await expect(page.locator('.u-over').first()).toBeVisible();
});

test('media page renders Vega-Lite and Plotly figures', async ({ page }) => {
  await page.goto('/#/media?project=vit-ablations&mfind=%5Eeval%2Fper_class%24');
  const vega = page.frameLocator('iframe[sandbox]').first();
  await expect(vega.locator('svg.marks')).toBeVisible({ timeout: 15000 });
  await page.goto('/#/media?project=vit-ablations&mfind=%5Eeval%2Fconfusion%24');
  const plotly = page.frameLocator('iframe[sandbox]').first();
  await expect(plotly.locator('.main-svg').first()).toBeVisible({ timeout: 15000 });
});

test('media page plays audio with the waveform and simple players', async ({ page }) => {
  await page.goto('/#/media?project=speech-denoise&mfind=%5Eaudio%2Fenhanced%24');
  const player = page.frameLocator('iframe[src="./audio.html"]').first();
  await expect(player.locator('#player[data-ready]')).toBeAttached({ timeout: 15000 });
  await expect(player.locator('#player[data-spectrogram]')).toBeAttached({ timeout: 15000 });
  await expect(player.locator('#duration')).toHaveText('0:02.600');
  await page.getByRole('combobox', { name: 'Spectrogram colors' }).selectOption('magma');
  await page.getByRole('combobox', { name: 'Frequency scale' }).selectOption('mel');
  await expect(page).toHaveURL(/cmap=magma/);
  await expect(page).toHaveURL(/fscale=mel/);
  await expect(player.locator('#player[data-spectrogram]')).toBeAttached({ timeout: 15000 });
  await page.getByRole('button', { name: 'simple' }).click();
  await expect(page).toHaveURL(/player=simple/);
  const audio = page.locator('audio').first();
  await expect(audio).toBeVisible();
  await expect.poll(() => audio.evaluate((a: HTMLAudioElement) => a.duration)).toBeCloseTo(2.6, 1);
});

test('custom fields: add a column, edit a cell, set a field on selected runs', async ({ page }) => {
  await page.goto('/#/runs?project=vit-ablations');
  await page.getByRole('button', { name: /Columns/ }).click();
  const add = page.getByRole('button', { name: 'Add field' });
  await expect(add).toBeDisabled();
  await page.getByPlaceholder('Field name, e.g. verdict').fill('grade');
  await add.click();
  await expect(page).toHaveURL(/cols=field(:|%3A)grade/);
  await page.getByTitle('Edit grade').first().click();
  await page.keyboard.type('A');
  await page.keyboard.press('Enter');
  await expect(page.getByTitle('Edit grade').first()).toHaveText('A');
  const boxes = page.locator('.body .row input[type=checkbox]');
  await boxes.nth(1).check();
  await boxes.nth(2).check();
  await page.getByRole('button', { name: 'Set field…' }).click();
  const dlg = page.getByRole('dialog', { name: 'Set a field on 2 runs' });
  await dlg.getByLabel('Field').fill('grade');
  await dlg.getByLabel('Value').fill('B');
  await dlg.getByRole('button', { name: 'Set field' }).click();
  await expect(dlg).toBeHidden();
  await expect(page.getByTitle('Edit grade').nth(1)).toHaveText('B');
  await expect(page.getByTitle('Edit grade').nth(2)).toHaveText('B');
});

test('chart legend: solo a series, then All and None', async ({ page }) => {
  await page.goto('/#/charts?q=where%20tags%20has%20sweep%20group%20by%20config.optim.lr');
  const chips = page.locator('.legend-chip');
  await expect(chips).toHaveCount(4);
  await chips.nth(1).dblclick();
  await expect(page.locator('.legend-chip.off')).toHaveCount(3);
  await expect(chips.nth(1)).not.toHaveClass(/off/);
  await chips.nth(1).click({ modifiers: ['Alt'] }); // soloing it again brings all back
  await expect(page.locator('.legend-chip.off')).toHaveCount(0);
  await page.getByRole('button', { name: 'None', exact: true }).click();
  await expect(page.locator('.legend-chip.off')).toHaveCount(4);
  await page.getByRole('button', { name: 'All', exact: true }).click();
  await expect(page.locator('.legend-chip.off')).toHaveCount(0);
});

test('save view asks in a themed dialog', async ({ page }) => {
  await page.goto('/#/runs');
  await page.getByRole('button', { name: /save (current )?view/i }).click();
  const dlg = page.getByRole('dialog', { name: 'Save the current view' });
  await expect(dlg).toBeVisible();
  await expect(dlg.getByLabel('Name')).toHaveValue('my-view');
  await page.keyboard.press('Escape');
  await expect(dlg).toBeHidden();
});

test('media page filters kinds, sets the grid and picks the best step', async ({ page }) => {
  await page.goto('/#/media?project=vit-ablations');
  const kinds = page.getByRole('group', { name: 'Kinds of media' });
  await kinds.getByRole('button', { name: /^Images/ }).dblclick();
  await expect(page).toHaveURL(/mkinds=image/);
  await expect(page.locator('section.section')).toHaveCount(1);
  await page.getByRole('combobox', { name: 'Columns' }).selectOption('2');
  await page.getByRole('combobox', { name: 'Rows per page' }).selectOption('1');
  await expect(page.locator('section.section figure')).toHaveCount(2);
  await page.getByRole('button', { name: 'Next page' }).click();
  await expect(page.locator('section.section figure')).toHaveCount(2);
  await page.getByRole('button', { name: 'best metric' }).click();
  await expect(page).toHaveURL(/mmode=best/);
  await expect(page.locator('figure .step').first()).toContainText('step');
});

test('add a media item to a report, then open and export it', async ({ page }) => {
  await page.goto('/#/media?project=vit-ablations&mfind=%5Esamples');
  await page.getByRole('button', { name: 'Add to a report' }).first().click();
  const dlg = page.getByRole('dialog');
  await dlg.getByLabel('Report').fill('e2e-report');
  await dlg.getByRole('button', { name: 'Add', exact: true }).click();
  await page.getByRole('button', { name: 'Open report' }).click();
  await expect(page).toHaveURL(/#\/reports/);
  await expect(page.getByRole('textbox', { name: 'Report text' })).toHaveValue(/media:.*samples\/augmented@/);
  await expect(page.locator('.preview img').first()).toBeVisible();
  const download = page.waitForEvent('download');
  await page.getByRole('link', { name: 'Export as .zip' }).click();
  expect((await download).suggestedFilename()).toBe('e2e-report.zip');
});

test('the demo report renders its embedded figures', async ({ page }) => {
  await page.goto('/#/reports?rview=preview');
  await page.getByRole('button', { name: /Augmentation findings/ }).click();
  await expect(page.locator('.preview img')).toHaveCount(2);
  const plotly = page.frameLocator('.preview iframe[sandbox]').first();
  await expect(plotly.locator('.main-svg').first()).toBeVisible({ timeout: 15000 });
});

test('run details show Markdown notes and typed properties', async ({ page }) => {
  await page.goto('/#/runs?project=vit-ablations');
  await page.getByRole('button', { name: 'cutmix-s0', exact: true }).click();
  await page.getByRole('button', { name: 'Notes', exact: true }).click();
  await expect(page.getByText('Best of the sweep', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Properties', exact: true }).click();
  await expect(page.locator('#prop-verdict')).toHaveValue('keep');
  await page.locator('#prop-gpu_hours').fill('7.25');
  await page.getByRole('button', { name: 'Save 1 change' }).click();
  await expect(page.getByRole('button', { name: 'Saved' })).toBeVisible();
  await page.getByRole('button', { name: 'Add property' }).click();
  const dlg = page.getByRole('dialog');
  await dlg.getByLabel('Name', { exact: true }).fill('split');
  await dlg.getByRole('combobox', { name: 'Type' }).selectOption('choice');
  await dlg.getByLabel('Options or unit').fill('train, val, test');
  await dlg.getByRole('button', { name: 'Add property' }).click();
  await expect(page.locator('#prop-split')).toBeVisible();
  // values stay inside their type: a choice is a menu, tags are toggled pills, numbers are checked
  await page.locator('#prop-split').selectOption('val');
  const topics = page.getByRole('group', { name: 'topics' });
  await topics.getByRole('button', { name: 'baseline' }).click();
  await expect(topics.getByRole('button', { name: 'baseline' })).toHaveAttribute('aria-pressed', 'true');
  await page.locator('#prop-gpu_hours').fill('lots');
  await expect(page.getByRole('alert')).toContainText('gpu_hours needs a number');
  await expect(page.getByRole('button', { name: /Save \d change/ })).toBeDisabled();
  await page.locator('#prop-gpu_hours').fill('8');
  await page.getByRole('button', { name: 'Save 3 changes' }).click();
  await expect(page.getByRole('button', { name: 'Saved' })).toBeVisible();
  // removing a property removes its definition and its values
  await page.getByRole('button', { name: 'Remove property split' }).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Remove' }).click();
  await expect(page.locator('#prop-split')).toHaveCount(0);
});

test('the server refuses a value outside a property', async ({ request }) => {
  const runs = (await (await request.get('/api/runs?project=vit-ablations')).json()).runs;
  const res = await request.post('/api/runs/annotate', {
    data: { keys: [runs[0].key], patch: { fields: { verdict: 'maybe' } } },
  });
  expect(res.status()).toBe(400);
  expect(await res.text()).toContain('verdict must be one of');
});

test('all metrics can be filtered with a regex, and run tags are pills', async ({ page }) => {
  await page.goto('/#/charts?project=vit-ablations&metric=val%2Facc');
  await page.getByRole('textbox', { name: 'Filter metrics' }).fill('^val/');
  await expect(page).toHaveURL(/cfind=%5Eval%2F/);
  await expect(page.locator('.sect-head .label')).toHaveText(['val']);
  await expect(page.getByRole('switch', { name: 'Ignore outliers' })).toBeVisible();
  await page.goto('/#/runs?project=vit-ablations');
  await expect(page.locator('.run .tagpill').first()).toBeVisible();
  await expect(page.locator('.config .tagpill')).toHaveCount(0);
});

test('charts grid pages small charts, and the main chart goes full screen', async ({ page }) => {
  await page.goto('/#/charts?project=vit-ablations&metric=val%2Facc');
  await page.getByRole('combobox', { name: 'Chart columns' }).selectOption('3');
  await page.getByRole('combobox', { name: 'Chart rows per page' }).selectOption('1');
  await expect(page).toHaveURL(/ccols=3/);
  const perClass = page.locator('.sect').filter({ hasText: 'per_class' });
  await expect(perClass.locator('.small')).toHaveCount(3);
  await page.getByRole('button', { name: 'Next charts of per_class' }).click();
  await expect(perClass.getByText('2 / 4')).toBeVisible();
  await page.getByRole('button', { name: 'Full screen' }).click();
  await expect(page.locator('.focus.full')).toBeVisible();
  await page.getByRole('button', { name: 'Exit full screen' }).click();
  await expect(page.locator('.focus.full')).toHaveCount(0);
});

test('add the main chart to a report, where it is drawn live', async ({ page }) => {
  await page.goto('/#/charts?project=vit-ablations&metric=val%2Facc');
  await expect(page.locator('.main canvas')).toBeVisible();
  await page.getByRole('button', { name: 'Add chart to a report' }).click();
  const dlg = page.getByRole('dialog');
  await dlg.getByLabel('Report').fill('e2e-charts');
  await dlg.getByRole('button', { name: 'Add', exact: true }).click();
  await page.getByRole('button', { name: 'Open report' }).click();
  await expect(page.getByRole('textbox', { name: 'Report text' })).toHaveValue(/files\/e2e-charts-\w+\.png "chart:/);
  await expect(page.locator('.preview .nb-chart canvas')).toBeVisible();
  await page.getByRole('button', { name: 'Open in Charts' }).click();
  await expect(page).toHaveURL(/#\/charts.*metric=val%2Facc/);
});

test('the browser tab is titled NuBoard', async ({ page }) => {
  await page.goto('/#/runs');
  await expect(page).toHaveTitle('NuBoard');
});

test('media legend shows and hides runs, and HTML items show their code', async ({ page }) => {
  await page.goto('/#/media?project=vit-ablations&mkinds=html&mrows=0');
  const cards = page.locator('section.section figure');
  await expect(cards).toHaveCount(8);
  await page.getByRole('button', { name: 'None', exact: true }).click();
  await expect(cards).toHaveCount(0);
  await page.locator('.run-chip').first().click();
  await expect(cards).toHaveCount(1);
  await page.locator('.run-chip').nth(1).dblclick();
  await expect(cards).toHaveCount(1);
  await page.getByRole('button', { name: 'All', exact: true }).click();
  await expect(cards).toHaveCount(8);
  await cards.first().getByRole('button', { name: 'code', exact: true }).click();
  const code = cards.first().getByRole('region', { name: /HTML source/ });
  await expect(code).toContainText('Eval report');
  await expect(code.locator('.ln').nth(2)).toHaveText('3');
});

test('sweeps: grid, full screen, and plots added to a report', async ({ page }) => {
  await page.goto('/#/sweeps?project=llm-pretrain');
  await page.getByRole('combobox', { name: 'Plot columns' }).selectOption('1');
  await page.getByRole('combobox', { name: 'Plot rows per page' }).selectOption('1');
  await expect(page.locator('.scatter')).toHaveCount(1);
  await page.getByRole('button', { name: 'Next plots' }).click();
  await page.getByRole('button', { name: 'Full screen' }).click();
  await expect(page.locator('.panel.full')).toBeVisible();
  await page.getByRole('button', { name: 'Add parallel coordinates to a report' }).click();
  const dlg = page.getByRole('dialog');
  await dlg.getByLabel('Report').fill('e2e-sweeps');
  await dlg.getByRole('button', { name: 'Add', exact: true }).click();
  await expect(page.locator('.panel.full')).toHaveCount(0); // left full screen for the dialog
  await page.getByRole('button', { name: 'Open report' }).click();
  await expect(page.getByRole('textbox', { name: 'Report text' })).toHaveValue(/"view:sweeps\?/);
  await page.getByRole('button', { name: 'Open in Sweeps' }).click();
  await expect(page).toHaveURL(/#\/sweeps/);
});

test('timeline goes full screen and into a report, which exports as HTML', async ({ page }) => {
  await page.goto('/#/timeline');
  await page.getByRole('button', { name: 'Full screen' }).click();
  await expect(page.locator('.panel.full')).toBeVisible();
  await page.getByRole('button', { name: 'Exit full screen' }).click();
  await page.getByRole('button', { name: 'Add timeline to a report' }).click();
  const dlg = page.getByRole('dialog');
  await dlg.getByLabel('Report').fill('e2e-timeline');
  await dlg.getByRole('button', { name: 'Add', exact: true }).click();
  await page.getByRole('button', { name: 'Open report' }).click();
  await expect(page.locator('.preview .nb-view img')).toBeVisible();
  const download = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Export as HTML' }).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Export', exact: true }).click();
  const file = await download;
  expect(file.suggestedFilename()).toBe('e2e-timeline.html');
  const html = await (await file.createReadStream()).toArray();
  const doc = Buffer.concat(html).toString();
  expect(doc).toContain('src="data:image/png;base64,');
  expect(doc).toContain('class="nbtheme"'); // switchable by default
  expect(doc).toMatch(/<footer>Exported with NuBoard \d+\.\d+\.\d+ from /);
  expect(doc).toContain('rel="icon"');
});

test('several media items go to a report together and export without a network', async ({ page, browser }) => {
  await page.goto('/#/media?project=vit-ablations&mkinds=figure&mcols=2&mrows=1');
  await page.getByRole('button', { name: 'Select for report' }).click();
  const boxes = page.getByRole('checkbox');
  await boxes.nth(0).check();
  await boxes.nth(2).check(); // the first card of the next key
  await expect(page.getByRole('toolbar', { name: 'Selected media' })).toContainText('2 selected');
  await page.getByRole('button', { name: 'Add 2 to report' }).click();
  const dlg = page.getByRole('dialog');
  await dlg.getByLabel('Report').fill('e2e-figures');
  await dlg.getByRole('button', { name: 'Add', exact: true }).click();
  await page.getByRole('button', { name: 'Open report' }).click();
  await expect(page.getByRole('textbox', { name: 'Report text' })).toHaveValue(
    /eval\/confusion@.*\n\n.*eval\/per_class@/s,
  );
  const download = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Export as HTML' }).click();
  const exp = page.getByRole('dialog');
  await exp.getByRole('button', { name: 'Dark', exact: true }).click();
  await exp.getByLabel('Footer', { exact: true }).fill('Figures for the group meeting');
  await exp.getByRole('switch').click(); // no logo
  await exp.getByRole('button', { name: 'Export', exact: true }).click();
  const path = test.info().outputPath('e2e-figures.html');
  await (await download).saveAs(path);
  const html = (await import('node:fs')).readFileSync(path, 'utf8');
  expect(html).not.toMatch(/<script[^>]+src=/);
  expect(html).toContain('data-theme="dark"');
  expect(html).toContain('<footer>Figures for the group meeting</footer>');
  expect(html).not.toContain('rel="icon"');
  // the file draws both figures with every network request blocked
  const ctx = await browser.newContext({ offline: true });
  await ctx.route(/^https?:/, (r) => r.abort());
  const off = await ctx.newPage();
  await off.goto('file://' + path);
  await expect(off.locator('.nbfig .main-svg').first()).toBeVisible();
  await expect(off.locator('.nbfig svg.marks')).toBeVisible();
  await ctx.close();
});

test('a saved chart is drawn live in the exported HTML and follows its theme', async ({ page, browser }) => {
  await page.goto('/#/reports?rproject=vit-ablations&report=augmentation-findings');
  const download = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Export as HTML' }).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Switchable', exact: true }).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Export', exact: true }).click();
  const path = test.info().outputPath('augmentation-findings.html');
  await (await download).saveAs(path);
  const ctx = await browser.newContext({ offline: true, colorScheme: 'light' });
  await ctx.route(/^https?:/, (r) => r.abort());
  const off = await ctx.newPage();
  await off.goto('file://' + path);
  await expect(off.locator('.nbplot canvas')).toBeVisible();
  await expect.poll(() => drawnPixels(off.locator('.nbpoints canvas'))).toBeGreaterThan(500);
  await expect(off.locator('html')).toHaveAttribute('data-theme', 'light');
  await off.getByRole('button', { name: 'Switch between light and dark theme' }).click();
  await expect(off.locator('html')).toHaveAttribute('data-theme', 'dark');
  await expect(off.locator('.nbplot canvas')).toBeVisible();
  await ctx.close();
});

test('about window and chart points', async ({ page }) => {
  await page.goto('/#/charts?project=vit-ablations&metric=val%2Facc');
  await page.getByRole('button', { name: 'About NuBoard' }).click();
  const about = page.getByRole('dialog', { name: 'NuBoard' });
  await expect(about).toContainText(/version \d+\.\d+\.\d+/);
  await expect(about).toContainText('MIT License');
  await expect(about.getByRole('link', { name: 'Documentation' })).toBeVisible();
  await about.getByRole('button', { name: 'Close' }).click();
  await expect(about).toBeHidden();
  const chart = page.locator('.main .chart').first();
  const box = (await chart.boundingBox())!;
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await expect(chart.locator('.nb-dot').first()).toBeVisible();
  await page.getByRole('switch', { name: 'Points' }).click();
  await expect(page).toHaveURL(/dots=0/);
  await expect(chart.locator('.nb-dot')).toHaveCount(0);
});

test('notes on a section of audio are saved, edited and deleted', async ({ page }) => {
  await page.goto('/#/media?project=speech-denoise&mfind=%5Eaudio%2Fenhanced%24');
  const frame = page.locator('iframe[src="./audio.html"]').first();
  const player = page.frameLocator('iframe[src="./audio.html"]').first();
  await expect(player.locator('#player[data-ready]')).toBeAttached({ timeout: 15000 });
  const box = (await player.locator('#waveform').boundingBox())!;
  await page.mouse.move(box.x + box.width * 0.2, box.y + 30);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width * 0.4, box.y + 30, { steps: 8 });
  await page.mouse.up();
  await player.getByRole('button', { name: 'Note', exact: true }).click();
  await player.locator('#note-text').fill('hiss here');
  await player.locator('#note-text').press('Enter');
  await expect(player.locator('.note-chip', { hasText: 'hiss here' })).toBeVisible();
  await expect(player.getByRole('button', { name: 'Edit note' })).toBeVisible();

  // kept in the run's annotations and shown again after a reload
  await page.reload();
  await expect(frame).toBeVisible();
  const mine = player.locator('.note-chip', { hasText: 'hiss here' });
  await expect(mine).toBeVisible({ timeout: 15000 });
  await mine.click();
  await player.getByRole('button', { name: 'Edit note' }).click();
  await expect(player.locator('#note-text')).toHaveValue('hiss here');
  await player.locator('#note-text').fill('hum');
  await player.locator('#note-text').press('Enter');
  await expect(player.locator('.note-chip', { hasText: 'hum' })).toBeVisible();
  await player.getByRole('button', { name: 'Edit note' }).click();
  await player.getByRole('button', { name: 'Delete' }).click();
  await expect(player.locator('.note-chip', { hasText: 'hum' })).toHaveCount(0);
});

/** How many pixels of a canvas differ from its top-left (background) pixel. */
async function drawnPixels(canvas: import('@playwright/test').Locator): Promise<number> {
  return canvas.evaluate((c: HTMLCanvasElement) => {
    const d = new Uint32Array(c.getContext('2d')!.getImageData(0, 0, c.width, c.height).data.buffer);
    return d.reduce((n, v) => n + (v !== d[0] ? 1 : 0), 0);
  });
}

test('point clouds are drawn and can be rotated', async ({ page }) => {
  await page.goto('/#/media?project=vit-ablations&mfind=embeddings');
  await expect(page.getByRole('button', { name: 'Point clouds 1' })).toBeVisible();
  const canvas = page.getByLabel('cutmix-s0 eval/embeddings');
  await expect(canvas).toBeVisible();
  await expect.poll(() => drawnPixels(canvas)).toBeGreaterThan(1000);
  const before = await canvas.screenshot();
  const box = (await canvas.boundingBox())!;
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width / 2 + 90, box.y + box.height / 2, { steps: 6 });
  await page.mouse.up();
  await expect.poll(async () => Buffer.compare(before, await canvas.screenshot())).not.toBe(0);
  await expect(page.getByText('3,000 points').first()).toBeVisible();
});

test('PR curves overlay every run and show counts on hover', async ({ page }) => {
  await page.goto('/#/media?project=vit-ablations&mfind=%5Eeval%2Fpr%2Fcat%24');
  const all = page.getByRole('img', { name: /Precision-recall curves of eval\/pr\/cat for all runs/ });
  await expect(all.locator('polyline')).toHaveCount(8);
  await expect(page.getByText(/cutmix-s0 · step 100 AP 0\.\d{3}/)).toBeVisible();
  // hover the middle point of one curve
  const [x, y] = await all
    .locator('polyline')
    .first()
    .evaluate((el: SVGPolylineElement) => {
      const pts = el.points;
      const p = pts.getItem(Math.floor(pts.numberOfItems / 2));
      const m = el.getScreenCTM()!;
      return [p.x * m.a + m.e, p.y * m.d + m.f];
    });
  await page.mouse.move(x, y);
  await expect(page.getByText(/^threshold 0\.\d{3}$/)).toBeVisible();
  await expect(page.getByText(/^TP \d+ · FP \d+ · TN \d+ · FN \d+$/)).toBeVisible();
});

test('tables compare steps, sort, filter and open a row', async ({ page }) => {
  await page.goto('/#/media?project=speech-denoise&mfind=eval%2Fsamples');
  await expect(page.getByRole('button', { name: 'Tables 1' })).toBeVisible();
  const card = page.locator('.tv').first();
  await expect(card.getByText(/^40 of 40 rows$/)).toBeVisible();
  await expect(card.getByText(/since step 20/)).toBeVisible();
  await card.getByRole('button', { name: /^pesq/ }).click();
  await expect(card.locator('th[aria-sort="ascending"]')).toHaveText(/pesq/);
  await expect(card.locator('td.heat[style*="color-mix"]').first()).toBeVisible();
  await card.getByLabel('Filter rows').fill('noise = babble and snr_in < 0');
  await expect(card.getByText(/^\d of 40 rows$/)).toBeVisible();
  await card.getByLabel('Filter rows').fill('nope < 1');
  await expect(card.getByText('no column named nope')).toBeVisible();
  await card.getByLabel('Filter rows').fill('');
  // the worst file carries its audio: opening the row shows its history and the player
  await card.locator('tbody tr').first().click();
  await expect(card.locator('.detail tr.now')).toBeVisible();
  await expect(card.locator('.detail iframe[src="./audio.html"]')).toBeVisible();
});

test('a report with a table and audio notes exports them', async ({ page, browser }) => {
  await page.goto('/#/reports?rproject=speech-denoise&report=listening-notes');
  const download = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Export as HTML' }).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Export', exact: true }).click();
  const path = test.info().outputPath('listening-notes.html');
  await (await download).saveAs(path);
  const ctx = await browser.newContext({ offline: true });
  const off = await ctx.newPage();
  await off.goto('file://' + path);
  await expect(off.locator('.nbtable tbody tr')).toHaveCount(40);
  await expect(off.getByText('Colors show the change since step 20.')).toBeVisible();
  await expect(off.locator('.nbnote')).toHaveCount(2);
  await expect(off.getByText('tonal blip (musical noise)')).toBeVisible();
  await ctx.close();
});

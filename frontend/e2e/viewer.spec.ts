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
  await page.getByRole('button', { name: 'config.json' }).click();
  await expect(page.locator('.line.del').first()).toBeVisible();
});

test('compare opens on screen and takes more than two runs', async ({ page }) => {
  await page.goto('/#/runs?project=llm-pretrain');
  const boxes = page.locator('.body .row input[type=checkbox]');
  for (const i of [0, 1, 2, 3]) await boxes.nth(i).check();
  await page.getByRole('button', { name: 'Compare' }).click();
  await expect(page.getByRole('heading', { name: /Compare 4 runs/ })).toBeInViewport();
  await expect(page.locator('.srow.head .run')).toHaveCount(4);
  await page.getByRole('button', { name: 'config.json' }).click();
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
  await page.goto('/#/media?project=vit-ablations&mkey=samples%2Faugmented');
  await expect(page.locator('figure img').first()).toBeVisible();
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
  await page.goto('/#/media?project=vit-ablations&mkey=eval%2Fper_class');
  const vega = page.frameLocator('iframe[sandbox]').first();
  await expect(vega.locator('svg.marks')).toBeVisible({ timeout: 15000 });
  await page.goto('/#/media?project=vit-ablations&mkey=eval%2Fconfusion');
  const plotly = page.frameLocator('iframe[sandbox]').first();
  await expect(plotly.locator('.main-svg').first()).toBeVisible({ timeout: 15000 });
});

test('media page plays audio with the waveform and simple players', async ({ page }) => {
  await page.goto('/#/media?project=speech-denoise&mkey=audio%2Fenhanced');
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

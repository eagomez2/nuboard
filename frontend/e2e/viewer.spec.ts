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

test('charts render grouped bands, a legend and small multiples', async ({ page }) => {
  await page.goto('/#/charts?q=where%20tags%20has%20sweep%20group%20by%20config.optim.lr');
  await expect(page.locator('.legend-chip')).toHaveCount(4);
  await expect(page.locator('.main canvas')).toBeVisible();
  await expect(page.locator('.small canvas').first()).toBeVisible();
  await page.getByRole('button', { name: 'wall time' }).click();
  await expect(page).toHaveURL(/x=time/);
});

test('media page shows logged images', async ({ page }) => {
  await page.goto('/#/media?project=vit-ablations&mkey=samples%2Faugmented');
  await expect(page.locator('figure img').first()).toBeVisible();
});

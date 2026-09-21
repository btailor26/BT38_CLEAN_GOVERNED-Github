import { test, expect } from '@playwright/test';

test('BT38 login page loads', async ({ page }) => {
  const pending = new Map<string, string>();
  let domContentLoaded = false;
  let loaded = false;

  page.on('request', request => {
    pending.set(request.url(), request.resourceType());
  });
  page.on('requestfinished', request => {
    pending.delete(request.url());
  });
  page.on('requestfailed', request => {
    pending.delete(request.url());
    console.log(
      '[bt38-login-diagnostic] requestfailed',
      request.resourceType(),
      request.url(),
      request.failure()?.errorText || 'unknown'
    );
  });
  page.on('domcontentloaded', () => {
    domContentLoaded = true;
    console.log('[bt38-login-diagnostic] domcontentloaded');
  });
  page.on('load', () => {
    loaded = true;
    console.log('[bt38-login-diagnostic] load');
  });

  try {
    // Keep the production gate unchanged: navigation must still reach the
    // browser load event. Use a shorter per-navigation timeout only so the
    // test has time to emit exact pending-request evidence before failing.
    await page.goto('/login', { waitUntil: 'load', timeout: 50000 });
  } catch (error) {
    console.log(
      '[bt38-login-diagnostic] lifecycle',
      JSON.stringify({
        url: page.url(),
        domContentLoaded,
        loaded,
        pending: Array.from(pending.entries()).map(([url, resourceType]) => ({
          resourceType,
          url,
        })),
      })
    );
    throw error;
  }

  await expect(page).toHaveTitle(/BT38|Inventory|Login/i);

  await expect(
    page.locator('input[type="password"]')
  ).toBeVisible();
});

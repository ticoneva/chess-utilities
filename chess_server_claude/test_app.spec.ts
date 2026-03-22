import { test, expect } from '@playwright/test';

const BASE_URL = 'http://127.0.0.1:5002';

test.describe('Chess Puzzle Generator', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto(BASE_URL);
  });

  test('page loads successfully and displays title', async ({ page }) => {
    await expect(page.locator('h4').first()).toHaveText('Chess Puzzle Generator');
  });

  test('board displays with pieces', async ({ page }) => {
    const board = page.locator('#board');
    await expect(board).toBeVisible();

    // Check that pieces are loaded
    const squares = await page.locator('.piece').count();
    expect(squares).toBeGreaterThan(0);
  });

  test('load sample PGN', async ({ page }) => {
    // Click Load Sample PGN button
    await page.click('#loadSampleBtn');

    // Wait for games list to appear
    await expect(page.locator('#gamesSection')).toBeVisible();

    // Check that games appear
    const games = page.locator('#gamesList .list-group-item');
    await expect(games.first()).toBeVisible();

    // Should have multiple games
    const gameCount = await games.count();
    expect(gameCount).toBeGreaterThan(0);
  });

  test('select a game', async ({ page }) => {
    // Load sample PGN first
    await page.click('#loadSampleBtn');
    await expect(page.locator('#gamesList .list-group-item')).toBeVisible();

    // Click first game
    await page.click('#gamesList .list-group-item:first-child');

    // Wait for navigation buttons to appear
    await expect(page.locator('#navigationSection')).toBeVisible();

    // Check move list appears
    await expect(page.locator('#moveListSection')).toBeVisible();
  });

  test('navigate through moves', async ({ page }) => {
    // Load and select game
    await page.click('#loadSampleBtn');
    await expect(page.locator('#gamesList .list-group-item')).toBeVisible();
    await page.click('#gamesList .list-group-item:first-child');
    await expect(page.locator('#navigationSection')).toBeVisible();

    // Get initial FEN
    let initialFen = await page.locator('#board').getAttribute('data-fen');

    // Click forward button
    await page.click('#nextBtn');
    await page.waitForTimeout(500); // Wait for board update

    let newFen = await page.locator('#board').getAttribute('data-fen');
    expect(newFen).not.toBe(initialFen);

    // Click back button
    await page.click('#prevBtn');
    await page.waitForTimeout(500);

    newFen = await page.locator('#board').getAttribute('data-fen');
    expect(newFen).toBe(initialFen);
  });

  test('keyboard navigation', async ({ page }) => {
    // Load and select game
    await page.click('#loadSampleBtn');
    await expect(page.locator('#gamesList .list-group-item')).toBeVisible();
    await page.click('#gamesList .list-group-item:first-child');
    await expect(page.locator('#navigationSection')).toBeVisible();

    const initialFen = await page.locator('#board').getAttribute('data-fen');

    // Use right arrow to move forward
    await page.keyboard.press('ArrowRight');
    await page.waitForTimeout(500);

    let newFen = await page.locator('#board').getAttribute('data-fen');
    expect(newFen).not.toBe(initialFen);

    // Use left arrow to move back
    await page.keyboard.press('ArrowLeft');
    await page.waitForTimeout(500);

    newFen = await page.locator('#board').getAttribute('data-fen');
    expect(newFen).toBe(initialFen);
  });

  test('upload PGN file', async ({ page }) => {
    // Create a simple PGN string
    const pgnContent = `
[Event "Test Game"]
[Site "?"]
[Date "2024.01.01"]
[White "Player 1"]
[Black "Player 2"]
[Result "*"]

1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 4. Ba4 Nf6 *
`;

    // Create file
    const fileInput = page.locator('#pgnFile');
    await fileInput.setInputContent(pgnContent);

    // Click upload button
    await page.click('#uploadBtn');

    // Wait for games list
    await expect(page.locator('#gamesSection')).toBeVisible({ timeout: 15000 });

    // Should show the uploaded game
    await expect(page.locator('#gamesList')).toContainText('Player 1');
  });

  test('switch between games', async ({ page }) => {
    await page.click('#loadSampleBtn');
    await expect(page.locator('#gamesList .list-group-item')).toBeVisible();

    // Select first game
    await page.click('#gamesList .list-group-item:first-child');
    await expect(page.locator('#navigationSection')).toBeVisible();

    const firstFen = await page.locator('#board').getAttribute('data-fen');

    // Select second game
    await page.click('#gamesList .list-group-item:nth-child(2)');
    await page.waitForTimeout(1000);

    const secondFen = await page.locator('#board').getAttribute('data-fen');
    expect(secondFen).not.toBe(firstFen);
  });

  test('toggle evaluation display', async ({ page }) => {
    // Load game
    await page.click('#loadSampleBtn');
    await page.click('#gamesList .list-group-item:first-child');
    await page.click('#nextBtn');
    await page.waitForTimeout(2000); // Wait for analysis

    // Evaluation section should be visible initially
    await expect(page.locator('#evaluationSection')).toBeVisible();

    // Turn off evaluation
    await page.uncheck('#showEvaluation');
    await expect(page.locator('#evaluationSection')).not.toBeVisible();

    // Turn it back on
    await page.check('#showEvaluation');
    await expect(page.locator('#evaluationSection')).toBeVisible();
  });

  test('puzzles tab displays puzzles (after analysis)', async ({ page, context }) => {
    // Load sample
    await page.click('#loadSampleBtn');

    // Select a game
    await page.click('#gamesList .list-group-item:first-child');

    // Click puzzles tab
    await page.click('button[data-bs-target="#puzzlesTab"]');

    // Puzzle settings should appear
    // Note: Analysis takes time, so we'll wait a bit
    await page.waitForTimeout(5000);

    // Puzzles section should have content (either loaded or analyzing)
    const puzzlesSection = page.locator('#puzzlesList');
    await expect(puzzlesSection).toBeVisible();
  });

  test('best moves tab', async ({ page }) => {
    await page.click('#loadSampleBtn');
    await page.click('#gamesList .list-group-item:first-child');
    await page.click('#nextBtn');
    await page.waitForTimeout(2000); // Wait for analysis

    // Best moves should appear
    await expect(page.locator('#bestMovesList')).toBeVisible();
  });

  test('settings persistence', async ({ page }) => {
    await page.click('#loadSampleBtn');
    await page.click('#gamesList .list-group-item:first-child');

    // Change number of best moves
    await page.fill('#numBestMoves', '2');
    await page.click('#numBestMoves');

    // Change time limit
    await page.fill('#timeLimit', '0.5');
    await page.click('#timeLimit');

    // Navigate to update settings
    await page.click('#nextBtn');
    await page.waitForTimeout(1000);

    // Check values
    await expect(page.locator('#numBestMovesValue')).toHaveText('2');
    await expect(page.locator('#timeLimitValue')).toHaveText('0.5s');
  });
});
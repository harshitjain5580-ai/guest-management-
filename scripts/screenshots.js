const crypto = require("node:crypto");
const fs = require("node:fs/promises");
const net = require("node:net");
const os = require("node:os");
const path = require("node:path");
const { spawn, spawnSync } = require("node:child_process");
const { setTimeout: delay } = require("node:timers/promises");
const { chromium } = require("playwright");

const root = path.resolve(__dirname, "..");
const outputDirectory = path.join(root, "docs", "screenshots");
const pages = [
  { route: "/login", name: "login" },
  { route: "/signup", name: "signup" },
  { route: "/forgot-password", name: "forgot-password" },
  { route: `/reset-password?token=${crypto.randomBytes(32).toString("base64url")}`, name: "reset-password" },
];

function pythonCommand() {
  if (process.env.PYTHON) return { command: process.env.PYTHON, prefix: [] };
  if (process.platform === "win32") {
    const launcher = spawnSync("py", ["-3", "-c", "import sys"], { stdio: "ignore" });
    if (launcher.status === 0) return { command: "py", prefix: ["-3"] };
  }
  const command = process.platform === "win32" ? "python" : "python3";
  const check = spawnSync(command, ["-c", "import sys"], { stdio: "ignore" });
  if (check.status !== 0) {
    throw new Error("Python 3 is required to run the Flask application. Set PYTHON to its executable path if needed.");
  }
  return { command, prefix: [] };
}

async function findFreePort() {
  const server = net.createServer();
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  const { port } = server.address();
  await new Promise((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
  return port;
}

async function waitForServer(baseUrl, child, getLogs) {
  const deadline = Date.now() + 30_000;
  while (Date.now() < deadline) {
    if (child.exitCode !== null) {
      throw new Error(`The Flask server exited early.\n${getLogs()}`);
    }
    try {
      const response = await fetch(`${baseUrl}/healthz`, { signal: AbortSignal.timeout(1_500) });
      if (response.ok) return;
    } catch {
      // The app may still be starting; retry until it is ready or the deadline passes.
    }
    await delay(350);
  }
  throw new Error(`The Flask server did not become ready.\n${getLogs()}`);
}

async function capturePage(browser, baseUrl, route, name, viewport) {
  const page = await browser.newPage({ viewport, deviceScaleFactor: 1 });
  await page.goto(`${baseUrl}${route}`, { waitUntil: "domcontentloaded" });
  await page.locator("body").waitFor();
  const documentWidth = await page.evaluate(() => document.documentElement.scrollWidth);
  if (documentWidth !== viewport.width) {
    throw new Error(`${name} page overflows its ${viewport.width}px viewport (document width: ${documentWidth}px).`);
  }
  await page.waitForTimeout(300);
  const filename = `${name}-${viewport.width === 390 ? "mobile" : "desktop"}.png`;
  await page.screenshot({
    path: path.join(outputDirectory, filename),
    fullPage: true,
    animations: "disabled",
  });
  await page.close();
  console.log(`Captured ${filename}`);
}

async function main() {
  const python = pythonCommand();
  const port = await findFreePort();
  const baseUrl = `http://127.0.0.1:${port}`;
  const temporaryDirectory = await fs.mkdtemp(path.join(os.tmpdir(), "guest-manager-screenshots-"));
  const databaseFile = path.join(temporaryDirectory, "screenshots.db");
  const databaseUrl = `sqlite:///${databaseFile.replaceAll("\\", "/")}`;
  const environment = {
    ...process.env,
    APP_ENV: "development",
    APP_SECRET: crypto.randomBytes(48).toString("base64url"),
    CLIENT_URL: baseUrl,
    PUBLIC_BASE_URL: baseUrl,
    COOKIE_SECURE: "false",
    DATABASE_URL: databaseUrl,
    PORT: String(port),
  };
  delete environment.SMTP_HOST;
  delete environment.SMTP_USERNAME;
  delete environment.SMTP_PASSWORD;
  delete environment.SMTP_FROM_EMAIL;

  const child = spawn(python.command, [...python.prefix, path.join(root, "app.py")], {
    cwd: root,
    env: environment,
    stdio: ["ignore", "pipe", "pipe"],
  });
  let logs = "";
  const rememberOutput = (chunk) => {
    logs = `${logs}${chunk.toString()}`.slice(-8000);
  };
  child.stdout.on("data", rememberOutput);
  child.stderr.on("data", rememberOutput);

  let browser;
  try {
    await fs.mkdir(outputDirectory, { recursive: true });
    await waitForServer(baseUrl, child, () => logs);
    browser = await chromium.launch({ headless: true });

    for (const viewport of [{ width: 1440, height: 1000 }, { width: 390, height: 844 }]) {
      for (const page of pages) {
        await capturePage(browser, baseUrl, page.route, page.name, viewport);
      }

      const dashboard = await browser.newPage({ viewport, deviceScaleFactor: 1 });
      await dashboard.goto(`${baseUrl}/signup`, { waitUntil: "domcontentloaded" });
      const email = `screenshots-${crypto.randomUUID()}@example.com`;
      const password = crypto.randomBytes(24).toString("base64url");
      await dashboard.locator("#email").fill(email);
      await dashboard.locator("#password").fill(password);
      await dashboard.locator('button[type="submit"]').click();
      await dashboard.waitForURL(`${baseUrl}/`);
      await dashboard.locator('#guestRows td[colspan="4"]').waitFor();
      if (viewport.width === 390) {
        const menuButton = dashboard.locator(".menu-button");
        const navigation = dashboard.locator("#primaryNavigation");
        await menuButton.click();
        if (!(await navigation.isVisible()) || (await menuButton.getAttribute("aria-expanded")) !== "true") {
          throw new Error("The mobile navigation did not open.");
        }
        await menuButton.click();
        if (await navigation.isVisible()) {
          throw new Error("The mobile navigation did not close.");
        }
      }
      const documentWidth = await dashboard.evaluate(() => document.documentElement.scrollWidth);
      if (documentWidth !== viewport.width) {
        throw new Error(`Dashboard overflows its ${viewport.width}px viewport (document width: ${documentWidth}px).`);
      }
      await dashboard.waitForTimeout(300);
      const filename = `dashboard-${viewport.width === 390 ? "mobile" : "desktop"}.png`;
      await dashboard.screenshot({
        path: path.join(outputDirectory, filename),
        fullPage: true,
        animations: "disabled",
      });
      await dashboard.close();
      console.log(`Captured ${filename}`);
    }
  } finally {
    if (browser) await browser.close();
    if (child.exitCode === null) {
      child.kill();
      await Promise.race([
        new Promise((resolve) => child.once("exit", resolve)),
        delay(5_000),
      ]);
    }
    await fs.rm(temporaryDirectory, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});

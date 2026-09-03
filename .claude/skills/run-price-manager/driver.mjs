// REPL driver for the price_manager Django app.
// stdin commands -> Playwright actions against a running `docker compose` stack.
// Designed for agents: wrap in tmux (or pipe a heredoc), send commands, read stdout.
import { chromium } from 'playwright';
import * as readline from 'node:readline';
import * as fs from 'node:fs';
import * as path from 'node:path';

const BASE_URL = process.env.BASE_URL || 'http://localhost:8000';
const SHOT_DIR = process.env.SCREENSHOT_DIR || path.resolve(process.cwd(), 'driver_shots');
fs.mkdirSync(SHOT_DIR, { recursive: true });

let browser = null;
let page = null;
const consoleMsgs = [];

function requirePage() {
  if (!page) throw new Error('not launched - run `launch` first');
  return page;
}

const COMMANDS = {
  async launch() {
    if (browser) return console.log('already launched');
    browser = await chromium.launch({ headless: true });
    const context = await browser.newContext();
    page = await context.newPage();
    page.on('console', (msg) => consoleMsgs.push({ type: msg.type(), text: msg.text() }));
    console.log('launched. base url:', BASE_URL);
  },

  async nav(arg) {
    const p = requirePage();
    const url = /^https?:\/\//.test(arg) ? arg : BASE_URL + (arg.startsWith('/') ? arg : '/' + arg);
    const resp = await p.goto(url, { waitUntil: 'domcontentloaded' });
    console.log('nav', url, '->', resp ? resp.status() : '(no response)');
  },

  async 'wait-for'(arg) {
    const p = requirePage();
    try {
      if (arg.startsWith('text=')) {
        await p.getByText(arg.slice(5)).first().waitFor({ timeout: 10_000 });
      } else {
        await p.waitForSelector(arg, { timeout: 10_000 });
      }
      console.log('found:', arg);
    } catch {
      console.log('TIMEOUT:', arg);
    }
  },

  async screenshot(name) {
    const p = requirePage();
    const f = path.join(SHOT_DIR, (name || `ss-${Date.now()}`) + '.png');
    await p.screenshot({ path: f, fullPage: true });
    console.log('screenshot:', f);
  },

  async click(sel) {
    const p = requirePage();
    await p.click(sel, { timeout: 10_000 });
    console.log('click', sel, '-> OK');
  },

  async fill(arg) {
    const p = requirePage();
    const sp = arg.indexOf(' ');
    const sel = sp === -1 ? arg : arg.slice(0, sp);
    const value = sp === -1 ? '' : arg.slice(sp + 1);
    await p.fill(sel, value, { timeout: 10_000 });
    console.log('fill', sel, '-> OK');
  },

  async press(key) {
    const p = requirePage();
    await p.keyboard.press(key);
    console.log('press', key, '-> OK');
  },

  async text(sel) {
    const p = requirePage();
    const out = sel ? await p.locator(sel).first().innerText() : await p.evaluate(() => document.body.innerText);
    console.log(out);
  },

  async eval(expr) {
    const p = requirePage();
    try {
      console.log(JSON.stringify(await p.evaluate(expr)));
    } catch (e) {
      console.log('ERROR:', e.message);
    }
  },

  async url() {
    const p = requirePage();
    console.log(p.url());
  },

  async sleep(ms) {
    await new Promise((r) => setTimeout(r, parseInt(ms, 10) || 1000));
    console.log('slept', ms || 1000, 'ms');
  },

  async console(arg) {
    const errorsOnly = (arg || '').includes('--errors');
    const msgs = errorsOnly ? consoleMsgs.filter((m) => m.type === 'error') : consoleMsgs;
    if (!msgs.length) console.log('(none)');
    for (const m of msgs) console.log(`[${m.type}] ${m.text}`);
  },

  // App-specific: log in as the throwaway agent test account created for driving.
  // Credentials: username=agent_test password=agent-test-pass-123 (superuser, created for this skill - not a real user's account).
  async login(arg) {
    const p = requirePage();
    const [user, pass] = (arg || 'agent_test agent-test-pass-123').split(' ');
    await p.goto(BASE_URL + '/accounts/login/', { waitUntil: 'domcontentloaded' });
    await p.fill('#id_username', user);
    await p.fill('#id_password', pass);
    await p.click('button[type=submit]');
    await p.waitForLoadState('domcontentloaded');
    console.log('login as', user, '-> now at', p.url());
  },

  async quit() {
    if (browser) await browser.close().catch(() => {});
    browser = null;
    page = null;
  },

  help() {
    console.log('commands:', Object.keys(COMMANDS).filter((c) => typeof COMMANDS[c] === 'function').join(', '));
  },
};

const rl = readline.createInterface({ input: process.stdin, output: process.stdout, prompt: 'driver> ' });
let closed = false;
rl.on('close', () => { closed = true; });
const safePrompt = () => { if (!closed) rl.prompt(); };

console.log('price_manager driver - "help" for commands, "launch" to start');
safePrompt();

// Sequential processing is required: readline's 'line' event fires for every
// buffered line as soon as stdin delivers them (e.g. a piped heredoc), so an
// event-listener handler would start `nav`/`click` before an awaited `launch`
// finishes. `for await` only pulls the next line once the current one resolves.
// (On a piped heredoc, stdin EOF closes `rl` right after the last line is
// yielded, so every prompt call after that must be a no-op, not a throw.)
for await (const line of rl) {
  const trimmed = line.trim();
  if (!trimmed) {
    safePrompt();
    continue;
  }
  const sp = trimmed.indexOf(' ');
  const cmd = sp === -1 ? trimmed : trimmed.slice(0, sp);
  const rest = sp === -1 ? '' : trimmed.slice(sp + 1);
  const fn = COMMANDS[cmd];
  if (!fn) {
    console.log('unknown:', cmd, '- try: help');
    safePrompt();
    continue;
  }
  try {
    await fn(rest);
  } catch (e) {
    console.log('ERROR:', e.message);
  }
  if (cmd === 'quit') break;
  safePrompt();
}
await COMMANDS.quit();
process.exit(0);

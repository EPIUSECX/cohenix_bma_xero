#!/usr/bin/env node
// Capture the Tax Mapping grid of Xero Settings in the light and the dark desk theme.
// The design skill's verify-ui.mjs captures the top of the form in light only. The grid
// sits lower, in a collapsed section, so this companion opens the section and scrolls to it.
//
//   FRAPPE_USER=... FRAPPE_PASSWORD=... node qa/visual/grid-shots.mjs [skill node_modules dir]
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";

const GRID = ".frappe-control[data-fieldname='tax_mapping']";
const VIEWPORTS = [
	{ width: 1440, height: 900 },
	{ width: 1280, height: 800 },
	{ width: 390, height: 844 },
];

const nodeModules =
	process.argv[2] || path.join(process.env.HOME, ".claude/skills/frappe-design-system/node_modules");
const require = createRequire(path.join(nodeModules, "x.js"));
const puppeteer = require("puppeteer-core");

const spec = JSON.parse(fs.readFileSync(path.resolve("qa/visual/spec.json"), "utf8"));
const out = path.resolve(spec.out || "qa/visual");
const route = spec.pages[0];
const user = process.env.FRAPPE_USER;
const password = process.env.FRAPPE_PASSWORD;
if (!user || !password) {
	console.error("FRAPPE_USER and FRAPPE_PASSWORD are required");
	process.exit(2);
}

const browser = await puppeteer.launch({
	executablePath: process.env.CHROME_PATH || "/usr/bin/chromium",
	headless: true,
	args: ["--no-sandbox", "--disable-dev-shm-usage"],
});
const page = await browser.newPage();
// Desk's own request helper carries the CSRF token; a bare fetch from the page does not.
const switchTheme = (theme) =>
	page.evaluate(async (theme) => {
		await frappe.xcall("frappe.core.doctype.user.user.switch_theme", { theme });
	}, theme);

await login();
const shots = { light: [], dark: [] };
try {
	shots.light = await capture("");
	await switchTheme("Dark");
	shots.dark = await capture("-dark");
} finally {
	await switchTheme("Light");
	await browser.close();
}
fs.writeFileSync(
	path.join(out, "dark-shots.json"),
	JSON.stringify({ shots: shots.dark, viewports: VIEWPORTS }, null, 2) + "\n"
);
console.log(`${shots.light.length + shots.dark.length} grid screenshots written`);

async function login() {
	await page.goto(`${spec.base}/login`, { waitUntil: "networkidle2" });
	await page.evaluate(
		async ({ user, password }) => {
			const response = await fetch("/api/method/login", {
				method: "POST",
				headers: { "Content-Type": "application/json", Accept: "application/json" },
				body: JSON.stringify({ usr: user, pwd: password }),
			});
			if (!response.ok) throw new Error(`login ${response.status}`);
		},
		{ user, password }
	);
	await page.goto(`${spec.base}/desk`, { waitUntil: "networkidle2" });
}

async function capture(suffix) {
	const files = [];
	for (const { width, height } of VIEWPORTS) {
		await page.setViewport({ width, height, deviceScaleFactor: 1 });
		await page.goto(`${spec.base}${route.path}`, { waitUntil: "networkidle2" });
		await page.waitForSelector(GRID);
		await showGrid();
		const file = path.join(out, `tax-mapping-${width}x${height}${suffix}.png`);
		await page.screenshot({ path: file, fullPage: false });
		files.push(path.relative(process.cwd(), file));
		const theme = await page.evaluate(() =>
			document.documentElement.getAttribute("data-theme-mode")
		);
		console.log(`tax-mapping ${width}x${height} theme=${theme}`);
	}
	return files;
}

async function showGrid() {
	await page.evaluate((selector) => {
		const grid = document.querySelector(selector);
		const section = grid.closest(".form-section");
		if (section.querySelector(".section-body").offsetParent === null) {
			section.querySelector(".section-head").click();
		}
		grid.scrollIntoView({ block: "center" });
	}, GRID);
	await new Promise((resolve) => setTimeout(resolve, 1200));
}

/**
 * Make Frappe UI's stylesheet safe to load inside Desk.
 *
 * 1. Scope every rule to `.xero-ui`, the element each page mounts on. Preflight and Frappe UI's
 *    base styles otherwise restyle the whole Desk (`*`, `html`, `body`, headings, buttons).
 * 2. Drop the design tokens Desk already defines. Frappe UI 1.0 and Desk 16.50 share one token set
 *    (`--surface-*`, `--ink-*`, `--outline-*`, ...); leaving Desk's values in charge keeps the pages
 *    identical to the Desk around them, including dark mode, which Desk switches on
 *    `html[data-theme]`. Tokens Desk does not define stay, scoped.
 */
import fs from "node:fs";
import path from "node:path";

const SCOPE = ".xero-ui";

function deskTokens() {
	// apps/xero/frontend -> apps/frappe/frappe/public/css/espresso
	const dir = path.resolve(import.meta.dirname, "../../frappe/frappe/public/css/espresso");
	const names = new Set();
	if (!fs.existsSync(dir)) return names;
	for (const file of fs.readdirSync(dir)) {
		if (!file.endsWith(".css")) continue;
		for (const m of fs
			.readFileSync(path.join(dir, file), "utf8")
			.matchAll(/(--[a-z0-9-]+)\s*:/g)) {
			names.add(m[1]);
		}
	}
	return names;
}

// `.dark` as a whole class only: `.dark\:bg-x` is a utility, not the theme selector.
const THEME_ROOT = /^(:root|html|:host|\.dark(?![\w\\-])|\[data-theme[^\]]*\])/;

function scopeSelector(sel) {
	const s = sel.trim();
	if (s.startsWith(SCOPE)) return s;
	// The document and its theme attribute are Desk's: put our root under them.
	if (/^(:root|html|:host|body)$/.test(s)) return SCOPE;
	const theme = s.match(/^(\.dark(?![\w\\-])|\[data-theme[^\]]*\])(.*)$/);
	if (theme)
		return theme[2].trim()
			? `${theme[1]} ${SCOPE} ${theme[2].trim()}`
			: `${theme[1]} ${SCOPE}`;
	return `${SCOPE} ${s}`;
}

export default function scopeToXeroUi() {
	const desk = deskTokens();
	return {
		postcssPlugin: "scope-to-xero-ui",
		Rule(rule) {
			if (rule.__xeroScoped) return;
			rule.__xeroScoped = true;
			if (rule.parent?.type === "atrule" && /keyframes/.test(rule.parent.name)) return;
			if (desk.size && rule.selectors.every((s) => THEME_ROOT.test(s.trim()))) {
				rule.walkDecls((decl) => {
					if (decl.prop.startsWith("--") && desk.has(decl.prop)) decl.remove();
				});
				if (!rule.nodes.length) {
					rule.remove();
					return;
				}
			}
			rule.selectors = rule.selectors.map(scopeSelector);
		},
	};
}
scopeToXeroUi.postcss = true;

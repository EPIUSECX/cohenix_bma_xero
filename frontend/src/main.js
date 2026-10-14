// Entry of the Xero Desk pages. xero_pages.bundle.js (a Desk bundle) imports this module at runtime
// and calls `mount(name, el, props)` from the page's on_page_show.
import { createApp } from "vue";
import "./style.css";

// One chunk per page, loaded the first time someone opens it.
const PAGES = {
	"xero-sync-dashboard": () => import("./pages/XeroDashboard.vue"),
};

/** The pages this bundle renders. */
export const pages = Object.keys(PAGES);

/** Mount a page into `el` and return the Vue app (the caller unmounts it on remount). */
export async function mount(name, el, props = {}) {
	const load = PAGES[name];
	if (!load) throw new Error(`Xero has no page called ${name}`);
	const { default: component } = await load();
	const app = createApp(component, props);
	// What Desk's SetVueGlobals gives its own Vue apps: translations and the frappe namespace.
	app.config.globalProperties.__ = window.__;
	app.config.globalProperties.frappe = window.frappe;
	el.classList.add("xero-ui");
	// Tooltips, dialogs and menus teleport to <body> by default, outside the `.xero-ui` scope their
	// styles live under. Name the mount element as the target so they are drawn with them.
	app.provide(Symbol.for("frappe-ui:portal-target"), el);
	app.mount(el);
	return app;
}

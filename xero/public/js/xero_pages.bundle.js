// The Xero Desk pages. Each page script loads this bundle and calls `xero.mount_page(name, wrapper)`
// on show. The pages are built with Frappe UI 1.0 in frontend/ (see frontend/src/main.js) and
// imported from here as one ES module, with its own Vue 3.5: Frappe UI 1.0 needs it, and Desk
// ships Vue 3.3.

frappe.provide("xero");

let frappe_ui_pages = null;

/** The page bundle (built by `bench build` into /assets/xero/frontend), imported once per session. */
function load_pages() {
	if (!frappe_ui_pages) {
		const base = "/assets/xero/frontend/";
		// Assets are cached for hours without a version, so boot.py stamps the build.
		const version = frappe.boot.xero_pages_version || 0;
		if (!document.querySelector("link[data-xero-ui]")) {
			const link = document.createElement("link");
			link.rel = "stylesheet";
			link.href = `${base}xero-pages.css?v=${version}`;
			link.dataset.xeroUi = "1";
			document.head.appendChild(link);
		}
		const url = `${base}xero-pages.js?v=${version}`;
		frappe_ui_pages = import(url).catch((e) => {
			frappe_ui_pages = null;
			throw e;
		});
	}
	return frappe_ui_pages;
}

/** Mount (or remount with the current route) the page `name` into the Desk page `wrapper`. */
xero.mount_page = async function (name, wrapper) {
	if (wrapper._xero_app) {
		wrapper._xero_app.unmount();
		wrapper._xero_app = null;
	}
	$(wrapper).addClass("xero-page");
	const $main = $(wrapper).find(".layout-main-section").empty();
	const el = $("<div></div>").appendTo($main).get(0);
	try {
		const pages = await load_pages();
		wrapper._xero_app = await pages.mount(name, el, {
			route: frappe.get_route().slice(1),
			page: wrapper.page,
		});
	} catch (e) {
		console.error(e);
		$(el).html(
			`<div class="text-muted" style="padding:16px">${__(
				"This page could not load. Reload the page, or ask your administrator to run bench build."
			)}</div>`
		);
	}
	return wrapper._xero_app;
};

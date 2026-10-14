// Rendered by the Frappe UI page in frontend/ (loaded by xero_pages.bundle.js): a Desk Page that
// hands a Vue 3 app its main section. Desk keeps the page head, the menu and the title.
frappe.pages["xero-sync-dashboard"].on_page_load = function (wrapper) {
	frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Xero Sync Dashboard"),
		single_column: true,
	});

	const page = wrapper.page;
	page.add_menu_item(__("Xero Settings"), () => frappe.set_route("Form", "Xero Settings"));
	page.add_menu_item(__("Account Mapping"), () => frappe.set_route("xero-account-mapping"));
	page.add_menu_item(__("Xero Logs"), () => frappe.set_route("List", "Xero Log"));
	page.add_menu_item(__("Export Logs"), () => {
		frappe
			.xcall("xero.xero.page.xero_sync_dashboard.xero_sync_dashboard.export_logs")
			.then((r) => {
				if (r && r.file_url) {
					window.open(r.file_url, "_blank");
					frappe.show_alert({ message: __("Logs exported"), indicator: "green" });
				} else {
					frappe.msgprint({
						title: __("Export Logs"),
						message: (r && r.error) || __("There was nothing to export."),
						indicator: "orange",
					});
				}
			});
	});
};

frappe.pages["xero-sync-dashboard"].on_page_show = function (wrapper) {
	frappe.require("xero_pages.bundle.js").then(() => xero.mount_page("xero-sync-dashboard", wrapper));
};

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
	const $parent = $(wrapper).find(".layout-main-section").empty();
	frappe.require("xero_dashboard.bundle.js").then(() => {
		window.xero_dashboard?.unmount?.();
		window.xero_dashboard = new frappe.ui.XeroDashboard({ wrapper: $parent, page: wrapper.page });
	});
};

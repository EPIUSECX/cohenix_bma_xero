// Copyright (c) 2024, Your Name and contributors
// For license information, please see license.txt

frappe.ui.form.on('Xero Account', {
	refresh: function(frm) {
		// Add custom buttons or functionality if needed
		if (frm.doc.status === 'ACTIVE') {
			frm.add_custom_button(__('Sync from Xero'), function() {
				frappe.call({
					method: 'xero.xero.doctype.xero_account.xero_account.sync_xero_accounts',
					callback: function(r) {
						if (r.message) {
							frappe.show_alert({
								message: 'Sync completed successfully',
								indicator: 'green'
							});
							frm.reload_doc();
						}
					}
				});
			});
		}
	}
});
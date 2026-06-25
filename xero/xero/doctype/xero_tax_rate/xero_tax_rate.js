// Copyright (c) 2024, Your Name and contributors
// For license information, please see license.txt

frappe.ui.form.on('Xero Tax Rate', {
	refresh: function(frm) {
		// Add custom buttons or functionality if needed
		if (frm.doc.status === 'ACTIVE') {
			frm.add_custom_button(__('Sync from Xero'), function() {
				frappe.call({
					method: 'xero.xero.doctype.xero_tax_rate.xero_tax_rate.sync_xero_tax_rates',
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

		// Show tax components summary
		if (frm.doc.tax_components && frm.doc.tax_components.length > 0) {
			let total_rate = 0;
			frm.doc.tax_components.forEach(component => {
				total_rate += component.rate || 0;
			});
			
			if (Math.abs(total_rate - (frm.doc.tax_rate || 0)) > 0.01) {
				frm.dashboard.add_comment(
					`Note: Component rates total ${total_rate.toFixed(2)}% but tax rate shows ${(frm.doc.tax_rate || 0).toFixed(2)}%`,
					'orange'
				);
			}
		}
	}
});
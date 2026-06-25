frappe.ui.form.on('Quotation', {
    refresh: function(frm) {
        // LITE Mode: Quotation sync is disabled. Only show button if
        // sync_quotes is explicitly enabled in Xero Settings.
        if (frm.doc.docstatus === 1 && !frm.is_dirty() && frm.doc.quotation_to === 'Customer') {
            frappe.db.get_single_value('Xero Settings', 'sync_quotes').then(enabled => {
                if (!enabled) return;

                frm.add_custom_button(__('Sync to Xero'), function() {
                    frappe.call({
                        method: 'xero.api.xero_quotes.enqueue_sync_quotation',
                        args: { doc: frm.doc, method: 'on_submit' },
                        callback: function(r) {
                            if (r.message) {
                                frappe.msgprint(__('Quotation sync to Xero has been queued.'));
                            }
                        }
                    });
                }, __('Actions'));
            });
        }
    }
});

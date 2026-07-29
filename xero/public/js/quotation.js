frappe.ui.form.on('Quotation', {
    refresh: function(frm) {
        // LITE Mode: Quotation sync is disabled. Only show button if
        // sync_quotes is explicitly enabled in Xero Settings.
        if (frm.doc.docstatus === 1 && !frm.is_dirty() && frm.doc.quotation_to === 'Customer') {
            frappe.db.get_single_value('Xero Settings', 'sync_quotes').then(enabled => {
                if (!enabled) return;

                frm.add_custom_button(__('Sync to Xero'), function() {
                    frappe.call({
                        method: 'xero.api.manual_sync.sync_document_to_xero',
                        args: { doctype: frm.doc.doctype, docname: frm.doc.name },
                        callback: function(r) {
                            if (r.message) {
                                frappe.msgprint(r.message);
                            }
                        }
                    });
                }, __('Actions'));
            });
        }
    }
});

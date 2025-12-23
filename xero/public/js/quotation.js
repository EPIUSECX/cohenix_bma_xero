frappe.ui.form.on('Quotation', {
    refresh: function(frm) {
        // Add Sync to Xero button only for submitted quotations that are not cancelled
        if (frm.doc.docstatus === 1 && !frm.is_dirty() && frm.doc.quotation_to === 'Customer') {
            // Check if already synced or if sync is in progress (optional)
            // if (frm.doc.xero_sync_status !== 'Synced') {

                frm.add_custom_button(__('Sync to Xero'), function() {
                    frappe.call({
                        method: 'xero.api.xero_quotes.enqueue_sync_quotation',
                        args: {
                            doc: frm.doc,
                            method: 'on_submit'
                        },
                        callback: function(r) {
                            if (r.message) {
                                frappe.msgprint(__('Quotation sync to Xero has been queued.'));
                                // Optionally update status field visually?
                                // frm.set_value('xero_sync_status', 'Queued'); // Need a 'Queued' status?
                            }
                        }
                    });
                }, __('Actions'));
            // }
        }
    }
});
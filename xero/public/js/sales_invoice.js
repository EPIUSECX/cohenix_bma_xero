frappe.ui.form.on('Sales Invoice', {
    refresh: function(frm) {
        // Add Sync to Xero button only for submitted invoices that are not cancelled
        if (frm.doc.docstatus === 1 && !frm.is_dirty()) {
            // Check if already synced or if sync is in progress (optional)
            // if (frm.doc.xero_sync_status !== 'Synced') {

                frm.add_custom_button(__('Sync to Xero'), function() {
                    frappe.call({
                        method: 'xero.api.xero_invoices.enqueue_sync_invoice',
                        args: {
                            doc_name: frm.doc.name,
                            doc_type: frm.doc.doctype
                        },
                        callback: function(r) {
                            if (r.message) {
                                // Message already shown by enqueue_sync_invoice
                                // Optionally update status field visually?
                                // frm.set_value('xero_sync_status', 'Queued'); // Need a 'Queued' status?
                            }
                        },
                        error: function(r) {
                            frappe.msgprint(__('Error queuing sync job. Check console.'));
                            console.error(r);
                        }
                    });
                }).addClass('btn-primary');

            // } // end optional status check
        }
    }
});

frappe.ui.form.on('Payment Entry', {
    refresh: function(frm) {
        // Add Sync to Xero button only for submitted entries
        // TODO: Check if Standalone Payment sync is enabled in Xero Settings?
        if (frm.doc.docstatus === 1 && !frm.is_dirty()) {
            // Avoid showing button if PE originated from Xero sync
            if (!frm.doc.reference_no || !frm.doc.reference_no.startsWith("XERO-")) {
                // Check if already synced or if sync is in progress (optional)
                // if (frm.doc.xero_sync_status !== 'Synced' && frm.doc.xero_sync_status !== 'Skipped') {

                    frm.add_custom_button(__('Sync to Xero'), function() {
                        frappe.call({
                            method: 'xero.api.xero_payments.enqueue_sync_payment_entry',
                            args: {
                                doc_name: frm.doc.name
                            },
                            callback: function(r) {
                                // Message shown by enqueue function
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
    }
});

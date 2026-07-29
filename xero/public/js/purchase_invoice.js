frappe.ui.form.on('Purchase Invoice', {
    refresh: function(frm) {
        // Add Sync to Xero button only for submitted invoices that are not cancelled
        if (frm.doc.docstatus === 1 && !frm.is_dirty()) {
            // Check if already synced or if sync is in progress (optional)
            // if (frm.doc.xero_sync_status !== 'Synced') {

                frm.add_custom_button(__('Sync to Xero'), function() {
                    frappe.call({
                        method: 'xero.api.manual_sync.sync_document_to_xero',
                        args: {
                            doctype: frm.doc.doctype,
                            docname: frm.doc.name
                        },
                        callback: function(r) {
                            if (r.message) {
                                frappe.msgprint(r.message);
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

frappe.ui.form.on('Journal Entry', {
    refresh: function(frm) {
        // Add Sync to Xero button only for submitted entries
        // TODO: Check if JE sync is enabled in Xero Settings? Requires async call or loading settings on form load.
        if (frm.doc.docstatus === 1 && !frm.is_dirty()) {
            // Check if already synced or if sync is in progress (optional)
            // if (frm.doc.xero_sync_status !== 'Synced') {

                frm.add_custom_button(__('Sync to Xero'), function() {
                    frappe.call({
                        method: 'xero.api.xero_journals.enqueue_sync_journal_entry',
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
});

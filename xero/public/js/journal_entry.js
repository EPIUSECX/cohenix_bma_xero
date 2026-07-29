frappe.ui.form.on('Journal Entry', {
    refresh: function(frm) {
        // LITE Mode: Journal Entry sync is disabled. Only show button if
        // sync_journal_entries is explicitly enabled in Xero Settings.
        if (frm.doc.docstatus === 1 && !frm.is_dirty()) {
            frappe.db.get_single_value('Xero Settings', 'sync_journal_entries').then(enabled => {
                if (!enabled) return;

                frm.add_custom_button(__('Sync to Xero'), function() {
                    frappe.call({
                        method: 'xero.api.manual_sync.sync_document_to_xero',
                        args: { doctype: frm.doc.doctype, docname: frm.doc.name },
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
            });
        }
    }
});

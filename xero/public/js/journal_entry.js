frappe.ui.form.on('Journal Entry', {
    refresh: function(frm) {
        // LITE Mode: Journal Entry sync is disabled. Only show button if
        // sync_journal_entries is explicitly enabled in Xero Settings.
        if (frm.doc.docstatus === 1 && !frm.is_dirty()) {
            frappe.db.get_single_value('Xero Settings', 'sync_journal_entries').then(enabled => {
                if (!enabled) return;

                frm.add_custom_button(__('Sync to Xero'), function() {
                    frappe.call({
                        method: 'xero.api.xero_journals.enqueue_sync_journal_entry',
                        args: { doc_name: frm.doc.name },
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

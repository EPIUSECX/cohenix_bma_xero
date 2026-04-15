frappe.ui.form.on('Item', {
    refresh: function(frm) {
        // LITE Mode: Item sync is disabled. Only show button if
        // sync_items is explicitly enabled in Xero Settings.
        if (!frm.is_new() && !frm.is_dirty()) {
            frappe.db.get_single_value('Xero Settings', 'sync_items').then(enabled => {
                if (!enabled) return;

                frm.add_custom_button(__('Sync to Xero'), function() {
                    frappe.call({
                        method: 'xero.api.xero_items.enqueue_sync_item',
                        args: { item_code: frm.doc.name },
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

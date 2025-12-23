frappe.ui.form.on('Item', {
    refresh: function(frm) {
        // Add Sync to Xero button only for saved items
        // TODO: Check if Item sync is enabled in Xero Settings?
        if (!frm.is_new() && !frm.is_dirty()) {
            // Check if already synced or if sync is in progress (optional)
            // if (frm.doc.xero_sync_status !== 'Synced') {

                frm.add_custom_button(__('Sync to Xero'), function() {
                    frappe.call({
                        method: 'xero.api.xero_items.enqueue_sync_item',
                        args: {
                            item_code: frm.doc.name // item_code is the name for Item doctype
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

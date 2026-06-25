frappe.ui.form.on('Bank Transaction', {
    refresh: function(frm) {
        // LITE Mode: Bank Transaction sync is disabled. Only show buttons if
        // sync_bank_transactions is explicitly enabled in Xero Settings.
        frappe.db.get_single_value('Xero Settings', 'sync_bank_transactions').then(enabled => {
            if (!enabled) return;

            if (frm.doc.docstatus === 1) {
                frm.add_custom_button(__('Sync to Xero'), function() {
                    frappe.call({
                        method: 'xero.api.xero_bank_transactions.sync_bank_transaction_to_xero',
                        args: { doc_name: frm.doc.name, doc_type: frm.doc.doctype },
                        callback: function(r) {
                            if (r.message) {
                                frappe.msgprint(__('Bank Transaction sync initiated. Check Xero Log for status.'));
                                frm.reload_doc();
                            }
                        },
                        error: function(r) {
                            frappe.msgprint(__('Failed to sync Bank Transaction to Xero: ') + r.message);
                        }
                    });
                }, __('Xero'));

                frm.add_custom_button(__('Reconcile with Xero'), function() {
                    let d = new frappe.ui.Dialog({
                        title: __('Reconcile Bank Transactions'),
                        fields: [
                            {
                                label: __('Bank Account'),
                                fieldname: 'bank_account',
                                fieldtype: 'Link',
                                options: 'Account',
                                default: frm.doc.account,
                                reqd: 1,
                                get_query: function() {
                                    return { filters: { 'account_type': 'Bank', 'is_group': 0 } };
                                }
                            },
                            { label: __('From Date'), fieldname: 'from_date', fieldtype: 'Date' },
                            { label: __('To Date'), fieldname: 'to_date', fieldtype: 'Date' }
                        ],
                        primary_action_label: __('Reconcile'),
                        primary_action: function(values) {
                            frappe.call({
                                method: 'xero.api.xero_bank_transactions.reconcile_bank_transactions',
                                args: values,
                                callback: function(r) {
                                    if (r.message) {
                                        frappe.msgprint(__('Bank reconciliation completed successfully.'));
                                        frm.reload_doc();
                                    }
                                },
                                error: function(r) {
                                    frappe.msgprint(__('Bank reconciliation failed: ') + r.message);
                                }
                            });
                            d.hide();
                        }
                    });
                    d.show();
                }, __('Xero'));
            }

            if (frm.doc.xero_bank_transaction_id) {
                frm.add_custom_button(__('View in Xero'), function() {
                    frappe.msgprint(__('Xero BankTransaction ID: {0}', [frm.doc.xero_bank_transaction_id]));
                }, __('Xero'));
            }
        });

        // Show sync status indicator (always, regardless of settings)
        if (frm.doc.xero_sync_status) {
            let color = 'gray';
            let message = frm.doc.xero_sync_status;
            switch(frm.doc.xero_sync_status) {
                case 'Synced': color = 'green'; message = __('Synced with Xero'); break;
                case 'Error': color = 'red'; message = __('Sync Error - Check Xero Log'); break;
                case 'Pending': color = 'orange'; message = __('Pending Sync'); break;
                case 'Skipped': color = 'gray'; message = __('Sync Skipped'); break;
            }
            frm.dashboard.add_indicator(__('Xero Status: {0}', [message]), color);
        }
    }
});

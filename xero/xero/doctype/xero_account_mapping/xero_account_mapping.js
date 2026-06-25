// Copyright (c) 2024, Your Name and contributors
// For license information, please see license.txt

frappe.ui.form.on("Xero Account Mapping", {
    refresh(frm) {
        // Set up dynamic options for Xero Account Code field
        setup_xero_account_options(frm);
    },

    xero_account_code(frm) {
        // When account code is selected, auto-populate name and ID
        if (frm.doc.xero_account_code) {
            populate_account_details(frm);
        }
    }
});

function setup_xero_account_options(frm) {
    // Get Xero account options and populate the dropdown
    frappe.call({
        method: 'xero.api.xero_accounts.get_xero_account_options',
        callback: function(r) {
            if (r.message && r.message.length > 0) {
                let options = r.message.map(opt => opt.value).join('\n');
                frm.set_df_property('xero_account_code', 'options', options);
            }
        },
        error: function(r) {
            console.log('Failed to fetch Xero account options:', r);
        }
    });
}

function populate_account_details(frm) {
    // When an account code is selected, populate the name and ID fields
    frappe.call({
        method: 'xero.api.xero_accounts.fetch_xero_accounts',
        callback: function(r) {
            if (r.message && r.message.length > 0) {
                let selected_account = r.message.find(acc => acc.code === frm.doc.xero_account_code);
                if (selected_account) {
                    frm.set_value('xero_account_name', selected_account.name);
                    frm.set_value('xero_account_id', selected_account.account_id);
                }
            }
        }
    });
}

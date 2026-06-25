// Copyright (c) 2024, Your Name and contributors
// For license information, please see license.txt

frappe.ui.form.on("Xero Tax Mapping", {
    refresh(frm) {
        // Set up dynamic options for Xero Tax Type Code field
        setup_xero_tax_options(frm);
    },

    xero_tax_type_code(frm) {
        // When tax type code is selected, auto-populate name and ID
        if (frm.doc.xero_tax_type_code) {
            populate_tax_details(frm);
        }
    }
});

function setup_xero_tax_options(frm) {
    // Get Xero tax type options and populate the dropdown
    frappe.call({
        method: 'xero.api.xero_accounts.get_xero_tax_type_options',
        callback: function(r) {
            if (r.message && r.message.length > 0) {
                let options = r.message.map(opt => opt.value).join('\n');
                frm.set_df_property('xero_tax_type_code', 'options', options);
            }
        },
        error: function(r) {
            console.log('Failed to fetch Xero tax type options:', r);
        }
    });
}

function populate_tax_details(frm) {
    // When a tax type code is selected, populate the name and rate fields
    frappe.call({
        method: 'xero.api.xero_accounts.fetch_xero_tax_rates',
        callback: function(r) {
            if (r.message && r.message.length > 0) {
                let selected_tax = r.message.find(tax => tax.tax_type === frm.doc.xero_tax_type_code);
                if (selected_tax) {
                    frm.set_value('xero_tax_type_name', selected_tax.name);
                    frm.set_value('xero_tax_rate', selected_tax.tax_rate);
                }
            }
        }
    });
}

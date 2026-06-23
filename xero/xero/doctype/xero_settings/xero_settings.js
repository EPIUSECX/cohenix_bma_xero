// Copyright (c) 2024, EPI-USE Global Services and contributors
// For license information, please see license.txt

// Global cache for Xero data to avoid repeated API calls
let xero_accounts_cache = null;
let xero_tax_rates_cache = null;

frappe.ui.form.on('Xero Settings', {
	refresh: function(frm) {
        frm.dashboard.clear_headline(); // Clear previous headlines
        frm.trigger("toggle_fields"); // Enable/disable based on master switch

        // Show OAuth error if redirected back from a failed connection attempt
        const urlParams = new URLSearchParams(window.location.search);
        const oauthError = urlParams.get('xero_oauth_error');
        if (oauthError) {
            frappe.msgprint({
                title: __('Xero Connection Failed'),
                message: decodeURIComponent(oauthError),
                indicator: 'red'
            });
            // Clean the URL so the message doesn't reappear on refresh
            window.history.replaceState({}, document.title, window.location.pathname);
        }

		// --- Connection Status & Buttons ---
		if (frm.doc.access_token && frm.doc.tenant_id && frm.doc.enable_xero_sync) {
            // Show connected status and add disconnect/check buttons
            const tenantLabel = frm.doc.tenant_name || frm.doc.tenant_id;
            frm.dashboard.set_headline(`Connected to Xero: ${tenantLabel}. Status: ${frm.doc.connection_status || 'Unknown'}`);

            frm.add_custom_button(__('Check Connection'), function() {
                frm.call('check_xero_connection').then(r => {
                    if (r.message) {
                        frm.set_value('connection_status', r.message.status);
                        frappe.show_alert({ message: `Connection Status: ${r.message.status}`, indicator: r.message.status === 'Active' ? 'green' : 'red' });
                    }
                });
            }, __('Actions'));

            frm.add_custom_button(__('Switch Organisation'), function() {
                frappe.call({
                    method: 'xero.utils.xero_client.get_available_tenants',
                    callback: function(r) {
                        const tenants = r.message || [];
                        if (tenants.length <= 1) {
                            frappe.msgprint(__('Only one Xero organisation is connected.'));
                            return;
                        }
                        const options = tenants.map(t => ({ value: t.id, label: t.name }));
                        frappe.prompt(
                            [{
                                label: __('Select Organisation'),
                                fieldname: 'tenant_id',
                                fieldtype: 'Select',
                                options: options.map(o => o.label),
                                reqd: 1
                            }],
                            function(values) {
                                const selected = tenants.find(t => t.name === values.tenant_id);
                                if (!selected) return;
                                frappe.call({
                                    method: 'xero.utils.xero_client.select_tenant',
                                    args: { tenant_id: selected.id },
                                    callback: function() { frm.reload_doc(); }
                                });
                            },
                            __('Switch Xero Organisation')
                        );
                    }
                });
            }, __('Actions'));

            frm.add_custom_button(__('Disconnect from Xero'), function() {
                frappe.confirm('Are you sure you want to disconnect from Xero? This will clear your tokens.', () => {
                    frm.call('disconnect_xero').then(() => {
                        frm.reload_doc(); // Reload to reflect changes
                    });
                });
            }, __('Actions'));

            frm.add_custom_button(__('Open Sync Dashboard'), function() {
                window.location.href = '/desk/xero-sync-dashboard/';
            }, __('Actions'));

        } else if (frm.doc.enable_xero_sync) {
            // Show connect button if sync is enabled but not connected
            frm.add_custom_button(__('Connect to Xero'), function() {
				frappe.call({
					method: "xero.utils.xero_client.get_auth_url",
                    callback: function(r) {
                        if (r.message) {
                            window.location.href = r.message;
                        } else {
                            frappe.msgprint(__('Could not get Xero authorization URL. Check Client ID.'));
                        }
                    },
                    error: function(r) {
                        frappe.msgprint(__('Error getting Xero authorization URL.'));
                        console.error(r);
                    }
                });
			}).addClass('btn-primary');

            frm.add_custom_button(__('Open Sync Dashboard'), function() {
                window.location.href = '/desk/xero-sync-dashboard/';
            }, __('Actions'));
        } else {
             frm.dashboard.set_headline('Xero Synchronization is Disabled.');
        }

        // --- Add buttons for managing mappings ---
        if (frm.doc.enable_xero_sync && frm.doc.tenant_id) {
            frm.add_custom_button(__('Sync Xero Accounts'), function() {
                sync_xero_accounts(frm);
            }, __("Mappings"));

            frm.add_custom_button(__('Sync Xero Tax Rates'), function() {
                sync_xero_tax_rates(frm);
            }, __("Mappings"));

            frm.add_custom_button(__('View Xero Accounts'), function() {
                frappe.show_alert({ message: 'Fetching Xero Accounts...', indicator: 'blue' });
                frappe.call({
                    method: 'xero.api.xero_accounts.fetch_and_update_account_mapping',
                    callback: function(r) {
                        if (r.message && r.message.length > 0) {
                            show_xero_accounts_dialog(r.message);
                        }
                    },
                    error: function(r) {
                        frappe.show_alert({ message: 'Failed to fetch Xero accounts', indicator: 'red' });
                    }
                });
            }, __("Mappings"));

            frm.add_custom_button(__('View Xero Tax Rates'), function() {
                frappe.show_alert({ message: 'Fetching Xero Tax Rates...', indicator: 'blue' });
                frappe.call({
                    method: 'xero.api.xero_accounts.fetch_and_update_tax_mapping',
                    callback: function(r) {
                        if (r.message && r.message.length > 0) {
                            show_xero_tax_rates_dialog(r.message);
                        }
                    },
                    error: function(r) {
                        frappe.show_alert({ message: 'Failed to fetch Xero tax rates', indicator: 'red' });
                    }
                });
            }, __("Mappings"));

            // Add button to view Xero data in dialog
            frm.add_custom_button(__('View Xero Data'), function() {
                let d = new frappe.ui.Dialog({
                    title: __('View Xero Data'),
                    fields: [
                        {
                            fieldtype: 'Button',
                            fieldname: 'view_accounts',
                            label: __('View Accounts'),
                            click: function() {
                                frappe.call({
                                    method: 'xero.api.xero_accounts.fetch_xero_accounts',
                                    callback: function(r) {
                                        if (r.message && r.message.length > 0) {
                                            d.hide();
                                            show_xero_accounts_dialog(r.message);
                                        }
                                    }
                                });
                            }
                        },
                        {
                            fieldtype: 'Button',
                            fieldname: 'view_tax_rates',
                            label: __('View Tax Rates'),
                            click: function() {
                                frappe.call({
                                    method: 'xero.api.xero_accounts.fetch_xero_tax_rates',
                                    callback: function(r) {
                                        if (r.message && r.message.length > 0) {
                                            d.hide();
                                            show_xero_tax_rates_dialog(r.message);
                                        }
                                    }
                                });
                            }
                        }
                    ]
                });
                d.show();
            }, __("Mappings"));
        }

        // --- Account Mapping Setup Section ---
        if (frm.doc.enable_xero_sync && frm.doc.tenant_id) {
            frm.trigger("render_mapping_setup");
        }
	},

    // -------------------------------------------------------------------------
    // Account Mapping Setup
    // -------------------------------------------------------------------------

    render_mapping_setup: function(frm) {
        const status      = frm.doc.mapping_status || 'Not Started';
        const mode        = frm.doc.setup_mode || 'Manual';
        const statusColor = { 'Complete': 'green', 'In Progress': 'blue', 'Review Required': 'orange', 'Not Started': 'grey' }[status] || 'grey';

        const $info = frm.fields_dict.mapping_setup_info.$wrapper;
        $info.html(`
            <div style="padding:8px 0;">
                <span class="indicator ${statusColor}">Mapping Status: <strong>${status}</strong></span>
                &nbsp;&nbsp;|&nbsp;&nbsp;
                <span>Mode: <strong>${mode}</strong></span>
            </div>
        `);

        // Analyse button — always available when connected
        frm.add_custom_button(__('Analyse Account Mapping'), function() {
            xero_run_mapping(frm, true);
        }, __("Account Mapping"));

        // Re-run (apply) button — visible once analysis has been done
        if (status !== 'Not Started' && mode !== 'Manual') {
            frm.add_custom_button(__('Apply Auto-Mapping'), function() {
                frappe.confirm(
                    mode === 'Xero as Source'
                        ? __('This will create missing ERPNext accounts based on your Xero chart of accounts and populate the mapping table. Continue?')
                        : __('This will populate the mapping table with matched accounts. Gaps will be flagged for review. Continue?'),
                    () => xero_run_mapping(frm, false)
                );
            }, __("Account Mapping"));
        }

        if (status === 'Review Required' || status === 'In Progress') {
            frm.add_custom_button(__('Review & Confirm Mapping'), function() {
                xero_show_mapping_review_dialog(frm);
            }, __("Account Mapping")).addClass('btn-warning');
        }

        if (status === 'Complete') {
            const $info2 = frm.fields_dict.mapping_setup_info.$wrapper;
            $info2.find('.xero-mapping-info').html(
                `<div class="alert alert-success" style="margin-top:8px;">
                    ✅ Account mapping is complete. All Xero accounts are mapped to ERPNext accounts.
                </div>`
            );
        }
    },

    setup_mode: function(frm) {
        frm.save().then(() => frm.trigger("render_mapping_setup"));
    },

    enable_xero_sync: function(frm) {
        frm.trigger("toggle_fields");
    },

    enable_sync_to_xero: function(frm) {
        frm.trigger("toggle_fields");
    },

    enable_sync_from_xero: function(frm) {
        frm.trigger("toggle_fields");
    },

    toggle_fields: function(frm) {
        const enabled = frm.doc.enable_xero_sync;

        // Core settings fields — toggle based on master switch
        const core_fields = [
            "connection_status", "client_id", "client_secret", "tenant_id", "access_token",
            "refresh_token", "token_expiry", "create_payment_entry_on_sync",
            "default_bank_account", "account_mapping", "tax_mapping"
        ];
        core_fields.forEach(field => {
            frm.toggle_enable(field, enabled);
            frm.set_df_property(field, 'read_only', !enabled);
        });

        // Directional master switches — toggle based on master switch
        frm.toggle_enable("enable_sync_to_xero", enabled);
        frm.toggle_enable("enable_sync_from_xero", enabled);

        // Per-entity outbound sub-toggles — require both master AND outbound direction
        const outbound_entities = [
            "sync_contacts_to_xero", "sync_items_to_xero", "sync_invoices_to_xero",
            "sync_bills_to_xero", "sync_credit_notes_to_xero", "sync_payments_to_xero"
        ];
        const outbound_enabled = enabled && frm.doc.enable_sync_to_xero;
        outbound_entities.forEach(field => {
            frm.toggle_enable(field, outbound_enabled);
        });

        // Per-entity inbound sub-toggles — require both master AND inbound direction
        const inbound_entities = [
            "sync_contacts_from_xero", "sync_items_from_xero", "sync_invoices_from_xero",
            "sync_bills_from_xero", "sync_credit_notes_from_xero", "sync_payments_from_xero"
        ];
        const inbound_enabled = enabled && frm.doc.enable_sync_from_xero;
        inbound_entities.forEach(field => {
            frm.toggle_enable(field, inbound_enabled);
        });

        // Refresh dependent fields
        frm.refresh_field("default_bank_account");
        frm.refresh_field("account_mapping");
        frm.refresh_field("tax_mapping");
    }
});

// Helper function to display Xero accounts in a dialog
function show_xero_accounts_dialog(accounts) {
    let dialog = new frappe.ui.Dialog({
        title: __('Xero Accounts'),
        size: 'large',
        fields: [
            {
                fieldtype: 'HTML',
                fieldname: 'accounts_html'
            }
        ]
    });

    let html = `
        <div class="table-responsive">
            <table class="table table-striped">
                <thead>
                    <tr>
                        <th>Code</th>
                        <th>Name</th>
                        <th>Type</th>
                        <th>Tax Type</th>
                        <th>Status</th>
                        <th>Currency</th>
                        <th>Payments Enabled</th>
                    </tr>
                </thead>
                <tbody>
    `;

    accounts.forEach(account => {
        html += `
            <tr>
                <td>${account.code || ''}</td>
                <td>${account.name || ''}</td>
                <td>${account.type || ''}</td>
                <td>${account.tax_type || ''}</td>
                <td><span class="indicator ${account.status === 'ACTIVE' ? 'green' : 'red'}">${account.status || ''}</span></td>
                <td>${account.currency_code || ''}</td>
                <td>${account.enable_payments ? '<i class="fa fa-check text-success"></i>' : '<i class="fa fa-times text-muted"></i>'}</td>
            </tr>
        `;
    });

    html += `
                </tbody>
            </table>
        </div>
        <p class="text-muted">Total accounts: ${accounts.length}</p>
    `;

    dialog.fields_dict.accounts_html.$wrapper.html(html);
    dialog.show();
}

// Helper function to display Xero tax rates in a dialog
function show_xero_tax_rates_dialog(tax_rates) {
    let dialog = new frappe.ui.Dialog({
        title: __('Xero Tax Rates'),
        size: 'large',
        fields: [
            {
                fieldtype: 'HTML',
                fieldname: 'tax_rates_html'
            }
        ]
    });

    let html = `
        <div class="table-responsive">
            <table class="table table-striped">
                <thead>
                    <tr>
                        <th>Name</th>
                        <th>Tax Type</th>
                        <th>Total Rate (%)</th>
                        <th>Status</th>
                        <th>Report Tax Type</th>
                        <th>Components</th>
                    </tr>
                </thead>
                <tbody>
    `;

    tax_rates.forEach(tax_rate => {
        let components_html = '';
        if (tax_rate.components && tax_rate.components.length > 0) {
            components_html = tax_rate.components.map(comp =>
                `${comp.name}: ${comp.rate}%${comp.is_compound ? ' (Compound)' : ''}`
            ).join('<br>');
        }

        html += `
            <tr>
                <td>${tax_rate.name || ''}</td>
                <td>${tax_rate.tax_type || ''}</td>
                <td>${tax_rate.tax_rate ? tax_rate.tax_rate.toFixed(2) : '0.00'}</td>
                <td><span class="indicator ${tax_rate.status === 'ACTIVE' ? 'green' : 'red'}">${tax_rate.status || ''}</span></td>
                <td>${tax_rate.report_tax_type || ''}</td>
                <td><small>${components_html}</small></td>
            </tr>
        `;
    });

    html += `
                </tbody>
            </table>
        </div>
        <p class="text-muted">Total tax rates: ${tax_rates.length}</p>
    `;

    dialog.fields_dict.tax_rates_html.$wrapper.html(html);
    dialog.show();
}

// --- Xero Data Sync Functions ---

function sync_xero_accounts(frm) {
    frappe.show_alert({ message: 'Syncing Xero Accounts...', indicator: 'blue' });
    
    frappe.call({
        method: 'xero.xero.doctype.xero_account.xero_account.sync_xero_accounts',
        callback: function(r) {
            if (r.message) {
                frappe.show_alert({
                    message: `Sync completed: ${r.message.created} created, ${r.message.updated} updated. You can now select Xero Accounts in mapping tables.`,
                    indicator: 'green'
                });
                frm.refresh_field('account_mapping');
            }
        },
        error: function(r) {
            frappe.show_alert({ message: 'Failed to sync Xero accounts', indicator: 'red' });
        }
    });
}

function sync_xero_tax_rates(frm) {
    frappe.show_alert({ message: 'Syncing Xero Tax Rates...', indicator: 'blue' });
    
    frappe.call({
        method: 'xero.xero.doctype.xero_tax_rate.xero_tax_rate.sync_xero_tax_rates',
        callback: function(r) {
            if (r.message) {
                frappe.show_alert({
                    message: `Sync completed: ${r.message.created} created, ${r.message.updated} updated. You can now select Xero Tax Rates in mapping tables.`,
                    indicator: 'green'
                });
                frm.refresh_field('tax_mapping');
            }
        },
        error: function(r) {
            frappe.show_alert({ message: 'Failed to sync Xero tax rates', indicator: 'red' });
        }
    });
}

// =============================================================================
// Account Mapping Setup helpers
// =============================================================================

function xero_run_mapping(frm, dry_run) {
    const label = dry_run ? 'Analysing account mapping...' : 'Running auto-mapping...';
    frappe.show_alert({ message: label, indicator: 'blue' });

    frm.call({
        method: 'run_account_auto_mapping',
        args: { dry_run: dry_run ? 1 : 0 },
        callback: function(r) {
            if (!r.message) {
                frappe.show_alert({ message: 'No response from server', indicator: 'red' });
                return;
            }
            const result = r.message;
            if (dry_run) {
                xero_show_mapping_analysis_dialog(frm, result);
            } else {
                frm.reload_doc();
                frappe.show_alert({
                    message: `Auto-mapping complete: ${result.summary.matched} matched, ${result.summary.created} accounts created, ${result.summary.unmatched_xero} still unmatched.`,
                    indicator: result.summary.unmatched_xero > 0 ? 'orange' : 'green'
                });
                if (result.summary.unmatched_xero > 0 || result.summary.unmatched_erpnext > 0) {
                    xero_show_mapping_review_dialog(frm, result);
                }
            }
        },
        error: function() {
            frappe.show_alert({ message: 'Failed to run auto-mapping', indicator: 'red' });
        }
    });
}

function xero_show_mapping_analysis_dialog(frm, result) {
    const s = result.summary;
    const mode = frm.doc.setup_mode || 'Manual';

    let html = `
        <div style="margin-bottom:12px;">
            <table class="table table-bordered table-sm">
                <tr><td><b>Total Xero accounts</b></td><td>${s.total_xero}</td></tr>
                <tr><td><b>Total ERPNext accounts</b></td><td>${s.total_erpnext}</td></tr>
                <tr><td><b>Already mapped</b></td><td>${s.already_mapped}</td></tr>
                <tr><td><b>Auto-matched</b></td><td>${s.matched}</td></tr>
                <tr><td><b>Xero accounts with no ERPNext match</b></td><td>${s.unmatched_xero}</td></tr>
                <tr><td><b>ERPNext accounts not in Xero</b></td><td>${s.unmatched_erpnext}</td></tr>
            </table>
        </div>`;

    if (result.matched.length) {
        html += `<h6>Matched (${result.matched.length})</h6>
        <div style="max-height:200px;overflow-y:auto;">
        <table class="table table-sm table-striped">
            <thead><tr><th>ERPNext Account</th><th>Xero Code</th><th>Xero Name</th><th>Confidence</th></tr></thead><tbody>`;
        result.matched.forEach(m => {
            const badge = m.confidence === 'High' ? 'success' : m.confidence === 'Medium' ? 'warning' : 'secondary';
            html += `<tr>
                <td>${m.erpnext_account}</td>
                <td>${m.xero_code || ''}</td>
                <td>${m.xero_name || ''}</td>
                <td><span class="badge badge-${badge}">${m.confidence}</span></td>
            </tr>`;
        });
        html += '</tbody></table></div>';
    }

    if (result.unmatched_xero.length) {
        html += `<h6 style="margin-top:10px;">Unmatched Xero accounts (${result.unmatched_xero.length})</h6>
        <div style="max-height:150px;overflow-y:auto;">
        <table class="table table-sm"><thead><tr><th>Code</th><th>Name</th><th>Type</th></tr></thead><tbody>`;
        result.unmatched_xero.forEach(a => {
            html += `<tr><td>${a.xero_code||''}</td><td>${a.xero_name||''}</td><td>${a.xero_type||''}</td></tr>`;
        });
        html += '</tbody></table></div>';
    }

    const applyLabel = mode === 'Xero as Source'
        ? 'Apply (create missing ERPNext accounts + map all)'
        : 'Apply (map matched accounts)';

    let d = new frappe.ui.Dialog({
        title: __('Account Mapping Analysis'),
        size: 'large',
        fields: [{ fieldtype: 'HTML', fieldname: 'analysis_html' }],
        primary_action_label: __(applyLabel),
        primary_action: function() {
            d.hide();
            xero_run_mapping(frm, false);
        },
        secondary_action_label: __('Close'),
        secondary_action: function() { d.hide(); }
    });
    d.fields_dict.analysis_html.$wrapper.html(html);
    d.show();
}

function xero_show_mapping_review_dialog(frm, result) {
    // If result not passed, fetch a fresh analysis
    if (!result) {
        frm.call({
            method: 'run_account_auto_mapping',
            args: { dry_run: 1 },
            callback: function(r) {
                if (r.message) xero_show_mapping_review_dialog(frm, r.message);
            }
        });
        return;
    }

    const mode = frm.doc.setup_mode || 'Manual';
    const pending = result.matched.filter(m => m.confidence !== 'High' || !m.xero_code);
    const unmatched = result.unmatched_xero || [];

    let rows_html = '';
    pending.forEach((m, idx) => {
        const badge = m.confidence === 'Medium' ? 'warning' : 'secondary';
        rows_html += `
        <tr>
            <td><input type="checkbox" class="confirm-row" data-idx="${idx}" checked></td>
            <td>${m.erpnext_account}</td>
            <td>${m.xero_code || ''}</td>
            <td>${m.xero_name || ''}</td>
            <td><span class="badge badge-${badge}">${m.confidence}</span></td>
        </tr>`;
    });

    let push_section = '';
    if (mode === 'ERPNext as Source' && unmatched.length > 0) {
        push_section = `
        <hr>
        <h6>Unmatched Xero accounts — no ERPNext equivalent found (${unmatched.length})</h6>
        <p class="text-muted small">These Xero accounts have no ERPNext counterpart. You can ignore them or push unmatched ERPNext accounts to Xero.</p>`;
    }

    let html = `
        <p>Review the suggested mappings below. Uncheck any you want to skip. Click <strong>Confirm Selected</strong> to write them to the mapping table.</p>
        <div style="max-height:350px;overflow-y:auto;">
        <table class="table table-sm table-bordered">
            <thead><tr>
                <th width="30"><input type="checkbox" id="check-all-mapping" checked></th>
                <th>ERPNext Account</th><th>Xero Code</th><th>Xero Name</th><th>Confidence</th>
            </tr></thead>
            <tbody id="mapping-review-tbody">${rows_html || '<tr><td colspan="5" class="text-muted text-center">No pending suggestions — all matched accounts are High confidence.</td></tr>'}</tbody>
        </table>
        </div>${push_section}`;

    let d = new frappe.ui.Dialog({
        title: __('Review & Confirm Account Mapping'),
        size: 'extra-large',
        fields: [{ fieldtype: 'HTML', fieldname: 'review_html' }],
        primary_action_label: __('Confirm Selected'),
        primary_action: function() {
            const checked = [];
            d.$wrapper.find('.confirm-row:checked').each(function() {
                const idx = parseInt($(this).data('idx'));
                checked.push(pending[idx]);
            });
            if (!checked.length) {
                frappe.show_alert({ message: 'No rows selected', indicator: 'orange' });
                return;
            }
            frm.call({
                method: 'confirm_account_mapping',
                args: { suggestions: JSON.stringify(checked) },
                callback: function(r) {
                    d.hide();
                    frm.reload_doc();
                    frappe.show_alert({
                        message: `${r.message.added} mapping(s) confirmed. Total mapped: ${r.message.total_mapped}.`,
                        indicator: 'green'
                    });
                }
            });
        }
    });

    d.fields_dict.review_html.$wrapper.html(html);

    // Select/deselect all
    d.$wrapper.find('#check-all-mapping').on('change', function() {
        d.$wrapper.find('.confirm-row').prop('checked', this.checked);
    });

    // Push to Xero button (Topology B only)
    if (mode === 'ERPNext as Source' && result.unmatched_erpnext && result.unmatched_erpnext.length > 0) {
        d.add_custom_action(__('Push Unmatched ERPNext Accounts to Xero'), function() {
            const names = result.unmatched_erpnext.map(a => a.erpnext_account);
            frappe.confirm(
                __(`Push ${names.length} ERPNext account(s) to Xero? This creates new accounts in your live Xero organisation.`),
                function() {
                    frm.call({
                        method: 'push_unmatched_to_xero',
                        args: { account_names: JSON.stringify(names) },
                        callback: function(r) {
                            const res = r.message;
                            d.hide();
                            frm.reload_doc();
                            frappe.show_alert({
                                message: `${res.created.length} account(s) pushed to Xero. ${res.errors.length} error(s).`,
                                indicator: res.errors.length ? 'orange' : 'green'
                            });
                            if (res.errors.length) {
                                frappe.msgprint({ title: 'Push Errors', message: res.errors.join('<br>'), indicator: 'orange' });
                            }
                        }
                    });
                }
            );
        });
    }

    d.show();
}

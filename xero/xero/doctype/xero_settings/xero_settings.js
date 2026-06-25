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

        // --- Account & Tax Mapping (single unified entry point) ---
        // The wizard auto-refreshes the live Xero chart + tax rates itself, so
        // the old per-utility Sync/View buttons are folded in.
        if (frm.doc.enable_xero_sync && frm.doc.tenant_id) {
            frm.trigger("render_mapping_setup");
        }
	},

    // -------------------------------------------------------------------------
    // Account Mapping Setup
    // -------------------------------------------------------------------------

    render_mapping_setup: function(frm) {
        const status = frm.doc.mapping_status || 'Not Started';
        const color  = { 'Complete': 'green', 'In Progress': 'blue', 'Review Required': 'orange', 'Not Started': 'grey' }[status] || 'grey';
        const $info  = frm.fields_dict.mapping_setup_info.$wrapper;
        $info.html(`
            <div style="padding:8px 0;">
                <span class="indicator ${color}">Account mapping: <strong>${status}</strong></span>
            </div>
        `);

        // One unified entry point — the wizard handles both directions + tax.
        xero_toggle_mapping_button(frm);
    },

    enable_xero_sync: function(frm) {
        frm.trigger("toggle_fields");
        xero_toggle_mapping_button(frm);
    },

    enable_sync_to_xero: function(frm) {
        frm.trigger("toggle_fields");
        xero_toggle_mapping_button(frm);
    },

    enable_sync_from_xero: function(frm) {
        frm.trigger("toggle_fields");
        xero_toggle_mapping_button(frm);
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

// -----------------------------------------------------------------------------
// Resolve Unmapped Accounts — map-or-create picker for ERPNext-only accounts
// -----------------------------------------------------------------------------
function _xero_esc(s) {
    if (s === null || s === undefined) return '';
    return String(s).replace(/[&<>"']/g, function(c) {
        return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
}

// Single unified entry point. Visible whenever connected; the wizard itself only
// shows the outbound (To Xero) section when that direction is enabled, and the
// backend blocks any write to Xero when it is off.
function xero_toggle_mapping_button(frm) {
    frm.remove_custom_button(__('Account & Tax Mapping'));
    if (frm.doc.enable_xero_sync && frm.doc.tenant_id) {
        frm.add_custom_button(__('Account & Tax Mapping'), function() {
            frappe.set_route('xero-account-mapping');
        }).addClass('btn-primary');
    }
}

// ===========================================================================
// Account & Tax Mapping wizard — one screen for both directions + tax
// ===========================================================================
function xero_show_mapping_wizard(frm) {
    frm.call({
        method: 'get_mapping_workspace',
        freeze: true,
        freeze_message: __('Refreshing the live Xero chart of accounts & tax rates…'),
        callback: function(r) {
            if (!r.message) {
                frappe.show_alert({ message: __('No response from server'), indicator: 'red' });
                return;
            }
            xero_render_mapping_wizard(frm, r.message);
        },
        error: function() {
            frappe.show_alert({ message: __('Failed to load mapping workspace'), indicator: 'red' });
        }
    });
}

function xero_render_mapping_wizard(frm, ws) {
    const dirs = ws.directions || {};
    const xeroAccts = ws.xero_accounts || [];
    const erpAccts = ws.erpnext_accounts || [];
    const xeroTax = ws.xero_tax_rates || [];

    // Reusable <option> builders
    const xeroAcctOptions = function(selCode) {
        let o = '<option value="">— select Xero account —</option>';
        xeroAccts.forEach(function(x) {
            const sel = selCode && selCode === x.code ? 'selected' : '';
            o += `<option value="${_xero_esc(x.code)}" data-name="${_xero_esc(x.name)}" data-id="${_xero_esc(x.account_id)}" ${sel}>${_xero_esc(x.code)} — ${_xero_esc(x.name)}</option>`;
        });
        return o;
    };
    const erpAcctOptions = function() {
        let o = '<option value="">— select ERPNext account —</option>';
        erpAccts.forEach(function(a) {
            o += `<option value="${_xero_esc(a.name)}">${_xero_esc(a.label)}</option>`;
        });
        return o;
    };
    const xeroTaxOptions = function(selCode) {
        let o = '<option value="">— select Xero tax rate —</option>';
        xeroTax.forEach(function(t) {
            const sel = selCode && selCode === t.tax_type ? 'selected' : '';
            o += `<option value="${_xero_esc(t.tax_type)}" data-name="${_xero_esc(t.name)}" data-rate="${_xero_esc(t.rate)}" ${sel}>${_xero_esc(t.name)} (${_xero_esc(t.rate)}%)</option>`;
        });
        return o;
    };

    const confBadge = function(c) {
        if (!c) return '';
        const cls = c === 'High' ? 'badge-success' : c === 'Medium' ? 'badge-warning' : 'badge-light';
        return `<span class="badge ${cls}">${_xero_esc(c)}</span>`;
    };

    // ---- Section B: ERPNext → Xero ----
    let toXeroRows = '';
    (ws.accounts_to_xero || []).forEach(function(u, i) {
        const sugg = u.suggested;
        const def = sugg ? 'map' : ((u.is_tax || !u.has_recent_error) ? 'skip' : 'create');
        let badges = '';
        if (u.has_recent_error) badges += '<span class="badge badge-danger" style="margin-right:4px;">Failing now</span>';
        if (u.is_tax) badges += '<span class="badge badge-warning" style="margin-right:4px;">Tax — use Tax section</span>';
        badges += `<span class="badge badge-light">${_xero_esc(u.root_type)}</span>`;
        toXeroRows += `
            <tr>
                <td><div><b>${_xero_esc(u.account_name)}</b></div><div style="font-size:11px;color:#8a8a8a;">${_xero_esc(u.erpnext_account)}</div><div style="margin-top:4px;">${badges}</div></td>
                <td><select class="form-control input-sm wz-action" data-sec="to" data-idx="${i}" style="font-size:12px;">
                    <option value="map" ${def === 'map' ? 'selected' : ''}>Map to existing</option>
                    <option value="create" ${def === 'create' ? 'selected' : ''}>Create in Xero</option>
                    <option value="skip" ${def === 'skip' ? 'selected' : ''}>Skip</option>
                </select></td>
                <td><select class="form-control input-sm wz-target" data-sec="to" data-idx="${i}" ${def === 'map' ? '' : 'disabled'} style="font-size:12px;">${xeroAcctOptions(sugg && sugg.code)}</select>
                    <div style="font-size:11px;color:${sugg ? '#0078C8' : '#999'};margin-top:2px;">${sugg ? 'Suggested (' + _xero_esc(sugg.confidence) + ')' : 'No existing match found'}</div></td>
            </tr>`;
    });

    // ---- Section A: Xero → ERPNext ----
    let fromXeroRows = '';
    (ws.accounts_from_xero || []).forEach(function(u, i) {
        const sugg = u.suggested_erpnext;
        const def = sugg ? 'map' : 'create';
        fromXeroRows += `
            <tr>
                <td><div><b>${_xero_esc(u.xero_name)}</b></div><div style="font-size:11px;color:#8a8a8a;">${_xero_esc(u.xero_code)} · ${_xero_esc(u.xero_type)}</div></td>
                <td><select class="form-control input-sm wz-action" data-sec="from" data-idx="${i}" style="font-size:12px;">
                    <option value="map" ${def === 'map' ? 'selected' : ''}>Map to existing</option>
                    <option value="create" ${def === 'create' ? 'selected' : ''}>Create in ERPNext</option>
                    <option value="skip">Skip</option>
                </select></td>
                <td><select class="form-control input-sm wz-target" data-sec="from" data-idx="${i}" ${def === 'map' ? '' : 'disabled'} style="font-size:12px;">${erpAcctOptions()}</select>
                    <div style="font-size:11px;color:${sugg ? '#0078C8' : '#999'};margin-top:2px;">${sugg ? 'Suggested: ' + _xero_esc(sugg) + ' (' + _xero_esc(u.confidence) + ')' : 'No existing match — will create'}</div></td>
            </tr>`;
    });

    // ---- Section C: tax ----
    let taxRows = '';
    (ws.tax || []).forEach(function(u, i) {
        const sugg = u.suggested;
        const def = sugg ? 'map' : 'skip';
        taxRows += `
            <tr>
                <td><div><b>${_xero_esc(u.erpnext_tax_template)}</b></div><div style="font-size:11px;color:#8a8a8a;">${_xero_esc(u.erpnext_rate)}%</div></td>
                <td><select class="form-control input-sm wz-action" data-sec="tax" data-idx="${i}" style="font-size:12px;">
                    <option value="map" ${def === 'map' ? 'selected' : ''}>Map to existing</option>
                    <option value="skip" ${def === 'skip' ? 'selected' : ''}>Skip</option>
                </select></td>
                <td><select class="form-control input-sm wz-target" data-sec="tax" data-idx="${i}" ${def === 'map' ? '' : 'disabled'} style="font-size:12px;">${xeroTaxOptions(sugg && sugg.tax_type)}</select>
                    <div style="font-size:11px;color:${sugg ? '#0078C8' : '#999'};margin-top:2px;">${sugg ? 'Suggested (' + _xero_esc(sugg.confidence) + ')' : 'No suggested match'}</div></td>
            </tr>`;
    });

    const section = function(title, subtitle, rows, count) {
        if (!count) {
            return `
                <div class="wz-card wz-done">
                    <span class="wz-done-icon"><i class="fa fa-check"></i></span>
                    <span class="wz-done-title">${title}</span>
                    <span class="wz-done-sub">${subtitle} — nothing needs attention</span>
                </div>`;
        }
        return `
            <div class="wz-card">
                <div class="wz-card-head">
                    <div>
                        <div class="wz-card-title">${title}</div>
                        <div class="wz-card-sub">${subtitle}</div>
                    </div>
                    <span class="badge badge-attention">${count} to review</span>
                </div>
                <div class="wz-card-body">
                    <table class="table wz-table">
                        <thead><tr><th>Account</th><th class="wz-col-action">Action</th><th>Target</th></tr></thead>
                        <tbody>${rows}</tbody>
                    </table>
                </div>
            </div>`;
    };

    const s = ws.summary || {};
    const needTotal = (s.need_to_xero || 0) + (s.need_from_xero || 0) + (s.need_tax || 0);
    let body = `
        <style>
            .xero-mapping-dialog .modal-content { border-radius: 10px; }
            .xero-mapping-dialog .modal-dialog { max-width: 1080px; }
            .xero-mapping-dialog .modal-body { background: #F4F6F8; }
            .xero-mapping-dialog .btn-primary, .xero-mapping-dialog .btn-modal-primary { background:#0078C8 !important; border-color:#0078C8 !important; color:#fff !important; }
            .xero-mapping-dialog .btn-primary:hover { background:#0063A6 !important; border-color:#0063A6 !important; }

            /* Summary strip */
            .xero-mapping-dialog .wz-summary { display:flex; align-items:center; gap:20px; flex-wrap:wrap; background:#fff; border:1px solid #E2E6EA; border-radius:8px; padding:12px 18px; margin-bottom:14px; }
            .xero-mapping-dialog .wz-stat { font-size:13px; color:#6B7785; }
            .xero-mapping-dialog .wz-stat b { font-size:18px; color:#1F2D3D; font-weight:700; margin-right:5px; }
            .xero-mapping-dialog .wz-stat.attn b { color:#0078C8; }
            .xero-mapping-dialog .wz-summary-actions { margin-left:auto; }

            /* Cards */
            .xero-mapping-dialog .wz-card { background:#fff; border:1px solid #E2E6EA; border-radius:8px; margin-bottom:14px; overflow:hidden; box-shadow:0 1px 2px rgba(9,30,66,0.06); }
            .xero-mapping-dialog .wz-card-head { display:flex; align-items:center; justify-content:space-between; padding:13px 18px; border-bottom:1px solid #E2E6EA; }
            .xero-mapping-dialog .wz-card-title { font-size:14px; font-weight:600; color:#1F2D3D; }
            .xero-mapping-dialog .wz-card-sub { font-size:12px; color:#6B7785; margin-top:1px; }
            .xero-mapping-dialog .wz-card-body { max-height:300px; overflow-y:auto; }

            /* Compact done card */
            .xero-mapping-dialog .wz-done { display:flex; align-items:center; gap:10px; padding:12px 18px; }
            .xero-mapping-dialog .wz-done-icon { width:22px; height:22px; border-radius:50%; background:#E9F8F1; color:#36B37E; display:inline-flex; align-items:center; justify-content:center; font-size:11px; flex-shrink:0; }
            .xero-mapping-dialog .wz-done-title { font-weight:600; color:#1F2D3D; font-size:14px; }
            .xero-mapping-dialog .wz-done-sub { color:#6B7785; font-size:12px; }

            /* Table */
            .xero-mapping-dialog .wz-table { margin:0; font-size:13px; }
            .xero-mapping-dialog .wz-table thead th { background:#F7F9FB; color:#6B7785; text-transform:uppercase; font-size:11px; letter-spacing:0.06em; font-weight:600; border-bottom:1px solid #E2E6EA; border-top:none; padding:9px 18px; position:sticky; top:0; z-index:1; }
            .xero-mapping-dialog .wz-table tbody td { padding:12px 18px; vertical-align:middle; border-top:1px solid #EEF1F4; }
            .xero-mapping-dialog .wz-table tbody tr:hover td { background:#F7F9FB; }
            .xero-mapping-dialog .wz-col-action { width:170px; }

            /* Controls */
            .xero-mapping-dialog .wz-action, .xero-mapping-dialog .wz-target { border:1px solid #D7DCE1; border-radius:6px; color:#1F2D3D; background:#fff; height:30px; width:100%; }
            .xero-mapping-dialog .wz-action:focus, .xero-mapping-dialog .wz-target:focus { border-color:#0078C8; box-shadow:0 0 0 3px #E8F6FC; outline:none; }
            .xero-mapping-dialog .wz-action[disabled], .xero-mapping-dialog .wz-target[disabled] { background:#F4F6F8; color:#9CA3AF; }
            .xero-mapping-dialog .wz-hint { font-size:11px; margin-top:3px; }

            /* Bulk buttons */
            .xero-mapping-dialog .wz-bulk { background:#fff; border:1px solid #D7DCE1; color:#1F2D3D; border-radius:6px; font-weight:600; margin-left:6px; }
            .xero-mapping-dialog .wz-bulk:hover { border-color:#0078C8; color:#0078C8; background:#E8F6FC; }

            /* Badges */
            .xero-mapping-dialog .badge { border-radius:9999px; font-weight:600; padding:3px 10px; border:1px solid transparent; font-size:11px; }
            .xero-mapping-dialog .badge-attention { background:#E8F6FC; color:#0078C8; border-color:#BFE3F5; }
            .xero-mapping-dialog .badge-danger { background:#FDECEE; color:#D0021B; border-color:#F6C6CC; }
            .xero-mapping-dialog .badge-warning { background:#FFF6E6; color:#E8910A; border-color:#FAE2B3; }
            .xero-mapping-dialog .badge-light { background:#F4F6F8; color:#6B7785; border-color:#E2E6EA; }
            .xero-mapping-dialog .badge-success { background:#E9F8F1; color:#1E7A52; border-color:#BFE9D4; }
        </style>
        <div class="wz-summary">
            <span class="wz-stat"><b>${s.mapped_accounts || 0}</b>accounts mapped</span>
            <span class="wz-stat"><b>${s.mapped_tax || 0}</b>tax templates mapped</span>
            <span class="wz-stat attn"><b>${needTotal}</b>need attention</span>
            <span class="wz-summary-actions">
                <button class="btn btn-xs wz-bulk" data-bulk="suggested">Accept all suggestions</button>
                <button class="btn btn-xs wz-bulk" data-bulk="skip">Set all to Skip</button>
            </span>
        </div>`;

    if (dirs.from_xero) body += section('From Xero → ERPNext', 'Xero accounts not yet in ERPNext', fromXeroRows, (ws.accounts_from_xero || []).length);
    if (dirs.to_xero) body += section('ERPNext → Xero', 'ERPNext accounts not yet in Xero — “Create” writes to Xero', toXeroRows, (ws.accounts_to_xero || []).length);
    body += section('Tax rates', 'ERPNext item tax templates → Xero tax rates', taxRows, (ws.tax || []).length);

    const d = new frappe.ui.Dialog({
        title: __('Account & Tax Mapping'),
        size: 'extra-large',
        fields: [{ fieldtype: 'HTML', fieldname: 'wz' }],
        primary_action_label: __('Apply'),
        primary_action: function() {
            const decisions = xero_collect_wizard_decisions(d, ws);
            const n = decisions.to_xero.length + decisions.from_xero.length + decisions.tax.length;
            if (!n) { frappe.show_alert({ message: __('Nothing selected to apply'), indicator: 'orange' }); return; }
            const createXero = decisions.to_xero.filter(function(x){ return x.action === 'create'; }).length;
            frappe.confirm(
                __('Apply {0} change(s)? {1} account(s) will be created live in your Xero organisation.', [n, createXero]),
                function() { d.hide(); xero_apply_workspace(frm, decisions); }
            );
        },
        secondary_action_label: __('Cancel'),
        secondary_action: function() { d.hide(); }
    });

    d.fields_dict.wz.$wrapper.html(body);
    d.$wrapper.addClass('xero-mapping-dialog');

    const $w = d.fields_dict.wz.$wrapper;
    $w.on('change', '.wz-action', function() {
        const sec = $(this).data('sec'), idx = $(this).data('idx');
        $w.find(`.wz-target[data-sec="${sec}"][data-idx="${idx}"]`).prop('disabled', $(this).val() !== 'map');
    });
    $w.on('click', '.wz-bulk', function(e) {
        e.preventDefault();
        const bulk = $(this).data('bulk');
        $w.find('.wz-action').each(function() {
            const $tgt = $w.find(`.wz-target[data-sec="${$(this).data('sec')}"][data-idx="${$(this).data('idx')}"]`);
            if (bulk === 'skip') { $(this).val('skip'); }
            else { // accept suggestions: map if a target is pre-selected, else create (accounts) / skip (tax)
                const hasSugg = $tgt.find('option:selected').val();
                if (hasSugg) $(this).val('map');
                else $(this).val($(this).find('option[value="create"]').length ? 'create' : 'skip');
            }
            $(this).trigger('change');
        });
    });

    d.show();
}

function xero_collect_wizard_decisions(d, ws) {
    const $w = d.fields_dict.wz.$wrapper;
    const out = { to_xero: [], from_xero: [], tax: [] };
    $w.find('.wz-action').each(function() {
        const sec = $(this).data('sec'), idx = $(this).data('idx'), action = $(this).val();
        if (action === 'skip') return;
        const $tgt = $w.find(`.wz-target[data-sec="${sec}"][data-idx="${idx}"]`);
        const $opt = $tgt.find('option:selected');
        if (sec === 'to') {
            const u = ws.accounts_to_xero[idx];
            const e = { erpnext_account: u.erpnext_account, action: action };
            if (action === 'map') { if (!$tgt.val()) return; e.xero_account_code = $tgt.val(); e.xero_account_name = $opt.data('name') || ''; e.xero_account_id = $opt.data('id') || ''; }
            out.to_xero.push(e);
        } else if (sec === 'from') {
            const u = ws.accounts_from_xero[idx];
            const e = { xero_account_id: u.xero_account_id, xero_code: u.xero_code, xero_name: u.xero_name, xero_type: u.xero_type, action: action };
            if (action === 'map') { if (!$tgt.val()) return; e.erpnext_account = $tgt.val(); }
            out.from_xero.push(e);
        } else if (sec === 'tax') {
            const u = ws.tax[idx];
            if (action !== 'map' || !$tgt.val()) return;
            out.tax.push({ erpnext_tax_template: u.erpnext_tax_template, action: 'map', xero_tax_type_code: $tgt.val(), xero_tax_type_name: $opt.data('name') || '', xero_tax_rate: $opt.data('rate') || 0 });
        }
    });
    return out;
}

function xero_apply_workspace(frm, decisions) {
    frm.call({
        method: 'apply_mapping_workspace',
        args: { decisions: JSON.stringify(decisions) },
        freeze: true,
        freeze_message: __('Applying mappings…'),
        callback: function(r) {
            if (!r.message) { frappe.show_alert({ message: __('No response'), indicator: 'red' }); return; }
            const res = r.message;
            const ob = res.outbound || {};
            const nCreatedErp = (res.created_erpnext || []).length;
            const nMapped = (res.mapped || []).length;
            const nTax = (res.tax_mapped || []).length;
            const errs = (res.errors || []).concat((ob.errors || []));
            let msg = `<b>${nMapped}</b> mapped · <b>${nCreatedErp}</b> created in ERPNext · <b>${nTax}</b> tax mapped.`;
            if (ob.queued) msg += `<br><b>${ob.count}</b> account(s) being created in Xero in the background — you will be notified when done.`;
            else if (ob.created) msg += `<br><b>${(ob.created || []).length}</b> created in Xero · <b>${(ob.mapped || []).length}</b> mapped to existing.`;
            if (errs.length) {
                msg += `<br><br><b style="color:#c0392b;">${errs.length} issue(s):</b><ul style="margin:6px 0 0 0;padding-left:18px;max-height:220px;overflow:auto;">`;
                errs.forEach(function(e) { msg += `<li>${_xero_esc(e)}</li>`; });
                msg += '</ul>';
            }
            frappe.msgprint({ title: __('Mapping applied'), message: msg, indicator: errs.length ? 'orange' : 'green' });
            if (ob.queued) {
                const on_done = function(data) {
                    frappe.realtime.off('xero_resolve_done', on_done);
                    frappe.show_alert({ message: __('Xero account creation finished: {0} created.', [(data.created || []).length]), indicator: 'green' }, 7);
                    frm.reload_doc();
                };
                frappe.realtime.on('xero_resolve_done', on_done);
            }
            frm.reload_doc();
        },
        error: function() { frappe.show_alert({ message: __('Failed to apply mappings'), indicator: 'red' }); }
    });
}

function xero_show_resolve_unmapped_dialog(frm) {
    frappe.show_alert({ message: __('Loading unmapped accounts…'), indicator: 'blue' });
    frm.call({
        method: 'get_unmapped_accounts_for_resolution',
        freeze: true,
        freeze_message: __('Fetching live Xero chart of accounts…'),
        callback: function(r) {
            if (!r.message) {
                frappe.show_alert({ message: __('No response from server'), indicator: 'red' });
                return;
            }
            const unmapped = r.message.unmapped || [];
            const xero_accounts = r.message.xero_accounts || [];

            if (!unmapped.length) {
                frappe.msgprint({
                    title: __('Nothing to resolve'),
                    message: __('Every ERPNext account already has a Xero mapping.'),
                    indicator: 'green'
                });
                return;
            }

            // Pre-build the Xero <option> list once (reused per row)
            let xeroOpts = '<option value="">— select Xero account —</option>';
            xero_accounts.forEach(function(x) {
                xeroOpts += `<option value="${_xero_esc(x.code)}" data-name="${_xero_esc(x.name)}" data-id="${_xero_esc(x.account_id)}">${_xero_esc(x.code)} — ${_xero_esc(x.name)}</option>`;
            });

            let rows = '';
            unmapped.forEach(function(u, idx) {
                const sugg = u.suggested;
                // Default: map where a match exists; otherwise only the accounts
                // that are actively failing default to Create — everything else
                // defaults to Skip so Apply never bulk-creates the whole chart.
                const defaultAction = sugg ? 'map' : ((u.is_tax || !u.has_recent_error) ? 'skip' : 'create');

                let badges = '';
                if (u.has_recent_error) badges += '<span class="badge badge-danger" style="margin-right:4px;">Failing now</span>';
                if (u.is_tax) badges += '<span class="badge badge-warning" style="margin-right:4px;">Tax — prefer Tax Mapping</span>';
                badges += `<span class="badge badge-light">${_xero_esc(u.root_type)}</span>`;

                // Xero select with the suggested code pre-selected
                let xeroSel = `<select class="form-control input-sm resolve-xero" data-idx="${idx}" ${defaultAction === 'map' ? '' : 'disabled'} style="font-size:12px;">`;
                xeroSel += '<option value="">— select Xero account —</option>';
                xero_accounts.forEach(function(x) {
                    const sel = (sugg && sugg.code === x.code) ? 'selected' : '';
                    xeroSel += `<option value="${_xero_esc(x.code)}" data-name="${_xero_esc(x.name)}" data-id="${_xero_esc(x.account_id)}" ${sel}>${_xero_esc(x.code)} — ${_xero_esc(x.name)}</option>`;
                });
                xeroSel += '</select>';

                rows += `
                <tr>
                    <td style="min-width:210px;">
                        <div><b>${_xero_esc(u.account_name)}</b></div>
                        <div style="font-size:11px;color:#8a8a8a;">${_xero_esc(u.erpnext_account)}</div>
                        <div style="margin-top:4px;">${badges}</div>
                    </td>
                    <td style="width:150px;">
                        <select class="form-control input-sm resolve-action" data-idx="${idx}" style="font-size:12px;">
                            <option value="map" ${defaultAction === 'map' ? 'selected' : ''}>Map to existing</option>
                            <option value="create" ${defaultAction === 'create' ? 'selected' : ''}>Create in Xero</option>
                            <option value="skip" ${defaultAction === 'skip' ? 'selected' : ''}>Skip</option>
                        </select>
                    </td>
                    <td>
                        ${xeroSel}
                        ${sugg ? `<div style="font-size:11px;color:#0078C8;margin-top:3px;">Suggested match (${_xero_esc(sugg.confidence)} confidence)</div>` : '<div style="font-size:11px;color:#999;margin-top:3px;">No existing match found</div>'}
                    </td>
                </tr>`;
            });

            const html = `
                <style>
                    .xero-resolve-dialog .modal-content { border-radius: 12px; }
                    .xero-resolve-dialog .btn-primary,
                    .xero-resolve-dialog .btn-modal-primary {
                        background: #0078C8 !important; border-color: #0078C8 !important; color: #fff !important;
                    }
                    .xero-resolve-dialog .btn-primary:hover,
                    .xero-resolve-dialog .btn-modal-primary:hover {
                        background: #0063A6 !important; border-color: #0063A6 !important;
                    }
                    .xero-resolve-dialog .bulk-set {
                        background: #fff; border: 1px solid #E2E6EA; color: #1F2D3D;
                        border-radius: 6px; font-weight: 600; margin-right: 6px;
                    }
                    .xero-resolve-dialog .bulk-set:hover {
                        border-color: #0078C8; color: #0078C8; background: #E8F6FC;
                    }
                    .xero-resolve-dialog .resolve-action,
                    .xero-resolve-dialog .resolve-xero {
                        border: 1px solid #E2E6EA; border-radius: 6px; color: #1F2D3D;
                    }
                    .xero-resolve-dialog .resolve-action:focus,
                    .xero-resolve-dialog .resolve-xero:focus {
                        border-color: #0078C8; box-shadow: 0 0 0 3px #E8F6FC; outline: none;
                    }
                    .xero-resolve-dialog table thead th {
                        color: #6B7785; text-transform: uppercase; font-size: 11px;
                        letter-spacing: 0.06em; font-weight: 600; border-bottom: 1px solid #E2E6EA;
                    }
                    .xero-resolve-dialog table tbody tr:hover td { background: #F4F6F8; }
                    .xero-resolve-dialog .badge { border-radius: 9999px; font-weight: 600; padding: 2px 9px; border: 1px solid transparent; }
                    .xero-resolve-dialog .badge-danger { background: #FDECEE; color: #D0021B; border-color: #F6C6CC; }
                    .xero-resolve-dialog .badge-warning { background: #FFF6E6; color: #E8910A; border-color: #FAE2B3; }
                    .xero-resolve-dialog .badge-light { background: #F4F6F8; color: #6B7785; border-color: #E2E6EA; }
                </style>
                <div style="margin-bottom:10px;font-size:13px;color:#6B7785;">
                    <b style="color:#1F2D3D;">${unmapped.length}</b> ERPNext account(s) have no Xero mapping — every transaction that touches one fails.
                    For each, <b>create</b> it in Xero or <b>map</b> it to an existing Xero account. Both write the mapping the sync uses.
                </div>
                <div style="margin-bottom:8px;">
                    <button class="btn btn-xs bulk-set" data-set="map">Use suggested where available</button>
                    <button class="btn btn-xs bulk-set" data-set="create">Set all to Create</button>
                    <button class="btn btn-xs bulk-set" data-set="skip">Set all to Skip</button>
                </div>
                <div style="max-height:440px;overflow-y:auto;border:1px solid #E2E6EA;border-radius:8px;">
                <table class="table table-sm" style="font-size:13px;margin-bottom:0;">
                    <thead><tr>
                        <th>ERPNext Account</th><th>Action</th><th>Map to existing Xero account</th>
                    </tr></thead>
                    <tbody>${rows}</tbody>
                </table>
                </div>`;

            const d = new frappe.ui.Dialog({
                title: __('Resolve Unmapped Accounts'),
                size: 'extra-large',
                fields: [{ fieldtype: 'HTML', fieldname: 'resolve_html' }],
                primary_action_label: __('Apply'),
                primary_action: function() {
                    const $w = d.fields_dict.resolve_html.$wrapper;
                    const resolutions = [];
                    $w.find('.resolve-action').each(function() {
                        const idx = $(this).data('idx');
                        const action = $(this).val();
                        if (action === 'skip') return;
                        const u = unmapped[idx];
                        const entry = { erpnext_account: u.erpnext_account, action: action };
                        if (action === 'map') {
                            const $sel = $w.find('.resolve-xero[data-idx="' + idx + '"]');
                            const code = $sel.val();
                            if (!code) return; // unselected map → skip silently
                            const $opt = $sel.find('option:selected');
                            entry.xero_account_code = code;
                            entry.xero_account_name = $opt.data('name') || '';
                            entry.xero_account_id = $opt.data('id') || '';
                        }
                        resolutions.push(entry);
                    });

                    if (!resolutions.length) {
                        frappe.show_alert({ message: __('Nothing selected to apply'), indicator: 'orange' });
                        return;
                    }

                    const createCount = resolutions.filter(function(x) { return x.action === 'create'; }).length;
                    frappe.confirm(
                        __('Apply {0} change(s)? {1} account(s) will be created live in your Xero organisation.', [resolutions.length, createCount]),
                        function() {
                            d.hide();
                            xero_apply_resolutions(frm, resolutions);
                        }
                    );
                },
                secondary_action_label: __('Cancel'),
                secondary_action: function() { d.hide(); }
            });

            d.fields_dict.resolve_html.$wrapper.html(html);
            d.$wrapper.addClass('xero-resolve-dialog');

            const $w = d.fields_dict.resolve_html.$wrapper;
            // Enable/disable the Xero dropdown based on the chosen action
            $w.on('change', '.resolve-action', function() {
                const idx = $(this).data('idx');
                $w.find('.resolve-xero[data-idx="' + idx + '"]').prop('disabled', $(this).val() !== 'map');
            });
            // Bulk setters
            $w.on('click', '.bulk-set', function(e) {
                e.preventDefault();
                const set = $(this).data('set');
                $w.find('.resolve-action').each(function() {
                    const idx = $(this).data('idx');
                    const u = unmapped[idx];
                    let val = set;
                    if (set === 'map' && !u.suggested) val = u.is_tax ? 'skip' : 'create';
                    $(this).val(val).trigger('change');
                });
            });

            d.show();
        },
        error: function() {
            frappe.show_alert({ message: __('Failed to load unmapped accounts'), indicator: 'red' });
        }
    });
}

function xero_show_resolution_result(res) {
    const nCreated = (res.created || []).length;
    const nMapped = (res.mapped || []).length;
    const errs = res.errors || [];

    let msg = `<b>${nCreated}</b> created in Xero · <b>${nMapped}</b> mapped to existing.`;
    if (errs.length) {
        msg += `<br><br><b style="color:#c0392b;">${errs.length} issue(s):</b><ul style="margin:6px 0 0 0;padding-left:18px;max-height:240px;overflow:auto;">`;
        errs.forEach(function(e) { msg += `<li>${_xero_esc(e)}</li>`; });
        msg += '</ul>';
    }
    frappe.msgprint({
        title: __('Resolution complete'),
        message: msg,
        indicator: errs.length ? 'orange' : 'green'
    });
}

function xero_apply_resolutions(frm, resolutions) {
    frm.call({
        method: 'resolve_unmapped_accounts',
        args: { resolutions: JSON.stringify(resolutions) },
        freeze: true,
        freeze_message: __('Submitting…'),
        callback: function(r) {
            if (!r.message) {
                frappe.show_alert({ message: __('No response from server'), indicator: 'red' });
                return;
            }
            const res = r.message;
            if (res.queued) {
                frappe.show_alert({
                    message: __('Creating {0} account(s) in Xero in the background — you can keep working. You will be notified when done.', [res.count]),
                    indicator: 'blue'
                }, 8);
                const on_done = function(data) {
                    frappe.realtime.off('xero_resolve_done', on_done);
                    xero_show_resolution_result(data);
                    frm.reload_doc();
                };
                frappe.realtime.on('xero_resolve_done', on_done);
            } else {
                xero_show_resolution_result(res);
                frm.reload_doc();
            }
        },
        error: function() {
            frappe.show_alert({ message: __('Failed to apply resolutions'), indicator: 'red' });
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

function xero_run_full_auto_map(frm) {
    // Show a blocking progress indicator — this call can take a while
    // when creating 100+ accounts with hierarchy
    const dlg = new frappe.ui.Dialog({
        title: __('Full Auto-Map in Progress'),
        fields: [{ fieldtype: 'HTML', fieldname: 'progress_html' }],
    });
    dlg.fields_dict.progress_html.$wrapper.html(`
        <div style="text-align:center;padding:24px 0;">
            <div class="spinner-border text-primary" role="status" style="width:2rem;height:2rem;"></div>
            <p style="margin-top:12px;">Fetching Xero accounts, matching, and creating missing ERPNext accounts...<br>
            <small class="text-muted">This may take up to a minute for large charts of accounts.</small></p>
        </div>
    `);
    dlg.show();
    // Prevent closing while running
    dlg.$wrapper.find('.btn-modal-close').hide();

    frappe.call({
        method: 'xero.xero.doctype.xero_settings.xero_settings.run_full_account_auto_map',
        freeze: false,   // we handle our own indicator
        callback: function(r) {
            dlg.hide();
            if (!r.message) {
                frappe.show_alert({ message: __('No response from server'), indicator: 'red' });
                return;
            }
            xero_show_full_map_result(frm, r.message);
        },
        error: function() {
            dlg.hide();
            frappe.show_alert({ message: __('Full auto-map failed. Check the Xero Log for details.'), indicator: 'red' });
        }
    });
}

function xero_show_full_map_result(frm, result) {
    const s      = result.summary;
    const status = s.mapping_status || 'Unknown';
    const statusBadge = status === 'Complete'
        ? `<span class="badge badge-success">Complete</span>`
        : `<span class="badge badge-warning">${status}</span>`;

    // Build summary table
    let html = `
        <h5>Result ${statusBadge}</h5>
        <table class="table table-bordered table-sm" style="margin-top:10px;">
            <tr><td>Total Xero accounts fetched</td><td><strong>${s.total_xero}</strong></td></tr>
            <tr><td>Already mapped (before run)</td><td>${s.already_mapped}</td></tr>
            <tr><td>Auto-matched to existing ERPNext accounts</td><td>${s.matched - s.created}</td></tr>
            <tr><td>ERPNext accounts created</td><td>${s.created}</td></tr>
            <tr><td>Written to mapping table this run</td><td>${s.written !== undefined ? s.written : s.matched}</td></tr>
            <tr><td>Still unmatched Xero accounts</td><td>${s.unmatched_xero}</td></tr>
        </table>`;

    // Created accounts — show hierarchy info
    if (result.created_accounts && result.created_accounts.length > 0) {
        const active   = result.created_accounts.filter(a => a.xero_status !== 'ARCHIVED');
        const archived = result.created_accounts.filter(a => a.xero_status === 'ARCHIVED');
        html += `<h6 style="margin-top:12px;">Created accounts (${result.created_accounts.length})</h6>`;
        if (active.length) {
            html += `<p class="text-muted small">${active.length} active, ${archived.length} disabled (archived in Xero)</p>`;
        }
        html += `<div style="max-height:200px;overflow-y:auto;">
            <table class="table table-sm table-striped">
                <thead><tr><th>ERPNext Account</th><th>Xero Code</th><th>Xero Name</th><th>Status</th></tr></thead>
                <tbody>`;
        result.created_accounts.forEach(a => {
            const badge = a.xero_status === 'ARCHIVED'
                ? '<span class="badge badge-secondary">Archived / Disabled</span>'
                : '<span class="badge badge-success">Active</span>';
            html += `<tr>
                <td><small>${a.erpnext_account}</small></td>
                <td>${a.xero_code || ''}</td>
                <td>${a.xero_name || ''}</td>
                <td>${badge}</td>
            </tr>`;
        });
        html += `</tbody></table></div>`;
    }

    // Errors
    if (result.errors && result.errors.length > 0) {
        html += `<div class="alert alert-warning" style="margin-top:10px;">
            <strong>${result.errors.length} error(s) during account creation:</strong><br>
            <small>${result.errors.slice(0, 10).join('<br>')}</small>
            ${result.errors.length > 10 ? `<br><em>...and ${result.errors.length - 10} more. Check Xero Log.</em>` : ''}
        </div>`;
    }

    // Still unmatched
    if (result.unmatched_xero && result.unmatched_xero.length > 0) {
        html += `<div class="alert alert-info" style="margin-top:8px;">
            <strong>${result.unmatched_xero.length} Xero account(s) could not be created</strong>
            (unsupported type or missing name). Check the Xero Log.
        </div>`;
    }

    let d = new frappe.ui.Dialog({
        title: __('Full Auto-Map Complete'),
        size: 'large',
        fields: [{ fieldtype: 'HTML', fieldname: 'result_html' }],
        primary_action_label: __('Close'),
        primary_action: function() { d.hide(); frm.reload_doc(); }
    });
    d.fields_dict.result_html.$wrapper.html(html);
    d.show();
}

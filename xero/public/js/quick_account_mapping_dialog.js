/**
 * Quick Account Mapping Dialog
 * Provides a fast, context-aware interface for mapping Xero accounts to ERPNext accounts
 */

class QuickAccountMappingDialog {
    constructor(unmapped_accounts) {
        this.unmapped_accounts = unmapped_accounts || [];
        this.mappings = {};
        this.dialog = null;
    }

    show() {
        if (this.unmapped_accounts.length === 0) {
            frappe.msgprint({
                title: __('No Unmapped Accounts'),
                message: __('All Xero accounts are already mapped. Great job!'),
                indicator: 'green'
            });
            return;
        }

        // Create dialog fields dynamically based on unmapped accounts
        const fields = this.build_dialog_fields();

        this.dialog = new frappe.ui.Dialog({
            title: __('Quick Account Mapping'),
            size: 'large',
            fields: fields,
            primary_action_label: __('Save All Mappings'),
            primary_action: (values) => {
                this.save_mappings(values);
            },
            secondary_action_label: __('Cancel')
        });

        this.dialog.show();
        
        // Add custom styling
        this.dialog.$wrapper.find('.modal-dialog').css('max-width', '800px');
    }

    build_dialog_fields() {
        const fields = [
            {
                fieldtype: 'HTML',
                fieldname: 'header_html',
                options: `
                    <div class="alert alert-info mb-3">
                        <h5><i class="fa fa-link"></i> Map ${this.unmapped_accounts.length} Unmapped Xero Account${this.unmapped_accounts.length > 1 ? 's' : ''}</h5>
                        <p class="mb-0">Select the corresponding ERPNext account for each Xero account below. Suggested accounts are pre-selected based on account type and name matching.</p>
                    </div>
                `
            }
        ];

        // Add fields for each unmapped account
        this.unmapped_accounts.forEach((account, index) => {
            // Section break for visual separation
            if (index > 0) {
                fields.push({
                    fieldtype: 'Section Break',
                    fieldname: `section_${index}`
                });
            }

            // Account info HTML
            fields.push({
                fieldtype: 'HTML',
                fieldname: `account_info_${index}`,
                options: `
                    <div class="xero-account-info mb-2 p-3" style="background: #f8f9fa; border-left: 4px solid #13B5EA; border-radius: 4px;">
                        <div class="row">
                            <div class="col-md-8">
                                <h6 class="mb-1">
                                    <i class="fa fa-building"></i> 
                                    <strong>${account.xero_code} - ${account.xero_name}</strong>
                                </h6>
                                <span class="badge badge-${this.get_type_badge_color(account.xero_type)}">${account.xero_type}</span>
                                ${account.error_count ? `<span class="badge badge-danger ml-2">${account.error_count} errors</span>` : ''}
                            </div>
                            <div class="col-md-4 text-right">
                                <small class="text-muted">Xero Account</small>
                            </div>
                        </div>
                    </div>
                `
            });

            // ERPNext account selection
            const default_account = account.suggested_accounts && account.suggested_accounts.length > 0 
                ? account.suggested_accounts[0].account_name 
                : null;

            fields.push({
                fieldtype: 'Link',
                fieldname: `erpnext_account_${index}`,
                label: __('Map to ERPNext Account'),
                options: 'Account',
                reqd: 1,
                default: default_account,
                get_query: () => {
                    return {
                        filters: {
                            'is_group': 0,
                            'disabled': 0
                        }
                    };
                },
                description: account.suggested_accounts && account.suggested_accounts.length > 0
                    ? `💡 Suggested: ${account.suggested_accounts.slice(0, 3).map(s => s.account_name).join(', ')}`
                    : 'Select an ERPNext account'
            });

            // Store xero_code for later retrieval
            fields.push({
                fieldtype: 'Data',
                fieldname: `xero_code_${index}`,
                label: 'Xero Code',
                hidden: 1,
                default: account.xero_code
            });
        });

        // Auto-retry checkbox
        fields.push({
            fieldtype: 'Section Break',
            fieldname: 'section_retry'
        });

        fields.push({
            fieldtype: 'Check',
            fieldname: 'auto_retry',
            label: __('Automatically retry failed syncs after mapping'),
            default: 1,
            description: 'If checked, the system will automatically re-queue syncs that failed due to missing account mappings.'
        });

        return fields;
    }

    get_type_badge_color(account_type) {
        const colors = {
            'REVENUE': 'success',
            'EXPENSE': 'warning',
            'ASSET': 'info',
            'LIABILITY': 'danger',
            'EQUITY': 'primary',
            'BANK': 'dark'
        };
        return colors[account_type] || 'secondary';
    }

    save_mappings(values) {
        // Extract mappings from dialog values
        const mappings = [];
        
        this.unmapped_accounts.forEach((account, index) => {
            const erpnext_account = values[`erpnext_account_${index}`];
            const xero_code = values[`xero_code_${index}`];
            
            if (erpnext_account && xero_code) {
                mappings.push({
                    xero_code: xero_code,
                    erpnext_account: erpnext_account
                });
            }
        });

        if (mappings.length === 0) {
            frappe.msgprint({
                title: __('No Mappings'),
                message: __('Please select at least one ERPNext account to map.'),
                indicator: 'orange'
            });
            return;
        }

        const auto_retry = values.auto_retry || false;

        // Show progress indicator
        frappe.show_alert({
            message: __('Saving mappings...'),
            indicator: 'blue'
        });

        // Call backend API
        frappe.call({
            method: 'xero.xero.doctype.xero_settings.xero_settings.XeroSettings.quick_map_accounts',
            args: {
                mappings: JSON.stringify(mappings),
                auto_retry: auto_retry
            },
            freeze: true,
            freeze_message: __('Saving account mappings...'),
            callback: (r) => {
                if (r.message && r.message.success) {
                    const result = r.message;
                    
                    // Build success message
                    let message = `Successfully mapped ${result.total_processed} account${result.total_processed > 1 ? 's' : ''}`;
                    if (result.mappings_added > 0) {
                        message += ` (${result.mappings_added} new)`;
                    }
                    if (result.mappings_updated > 0) {
                        message += ` (${result.mappings_updated} updated)`;
                    }
                    
                    if (auto_retry && result.retry_results) {
                        message += `\n\nRetried ${result.retry_results.retried_count} failed sync${result.retry_results.retried_count > 1 ? 's' : ''}`;
                    }
                    
                    frappe.msgprint({
                        title: __('Mappings Saved'),
                        message: message,
                        indicator: 'green'
                    });
                    
                    // Close dialog
                    this.dialog.hide();
                    
                    // Refresh dashboard if it exists
                    if (window.dashboard) {
                        setTimeout(() => {
                            window.dashboard.refresh_current_tab();
                        }, 1000);
                    }
                } else {
                    frappe.msgprint({
                        title: __('Error'),
                        message: r.message?.error || __('Failed to save mappings'),
                        indicator: 'red'
                    });
                }
            },
            error: (r) => {
                frappe.msgprint({
                    title: __('Error'),
                    message: r.message || __('An error occurred while saving mappings'),
                    indicator: 'red'
                });
            }
        });
    }

    static open_from_errors(days = 7) {
        /**
         * Static method to open dialog with unmapped accounts from recent errors
         */
        frappe.call({
            method: 'xero.xero.page.xero_sync_dashboard.xero_sync_dashboard.get_unmapped_accounts_from_errors',
            args: { days: days },
            freeze: true,
            freeze_message: __('Analyzing errors...'),
            callback: (r) => {
                if (r.message && r.message.success) {
                    if (r.message.unmapped_accounts.length === 0) {
                        frappe.msgprint({
                            title: __('All Accounts Mapped'),
                            message: __('No unmapped accounts found in recent errors. All account mappings are configured!'),
                            indicator: 'green'
                        });
                        return;
                    }
                    
                    const dialog = new QuickAccountMappingDialog(r.message.unmapped_accounts);
                    dialog.show();
                } else {
                    frappe.msgprint({
                        title: __('Error'),
                        message: r.message?.error || __('Failed to fetch unmapped accounts'),
                        indicator: 'red'
                    });
                }
            }
        });
    }

    static open_for_specific_codes(account_codes) {
        /**
         * Static method to open dialog for specific Xero account codes
         * @param account_codes: Array of Xero account codes (e.g., ['200', '310'])
         */
        if (!account_codes || account_codes.length === 0) {
            frappe.msgprint(__('No account codes provided'));
            return;
        }

        // Fetch details for these specific codes
        frappe.call({
            method: 'xero.xero.page.xero_sync_dashboard.xero_sync_dashboard.get_account_suggestions',
            args: { xero_account_code: account_codes[0] },  // Start with first code
            callback: (r) => {
                if (r.message && r.message.success) {
                    // Build unmapped accounts array
                    const unmapped_accounts = [{
                        xero_code: r.message.xero_account.account_code,
                        xero_name: r.message.xero_account.account_name,
                        xero_type: r.message.xero_account.account_type,
                        suggested_accounts: r.message.suggestions
                    }];
                    
                    const dialog = new QuickAccountMappingDialog(unmapped_accounts);
                    dialog.show();
                } else {
                    frappe.msgprint({
                        title: __('Error'),
                        message: __('Failed to fetch account details'),
                        indicator: 'red'
                    });
                }
            }
        });
    }
}

// Make globally accessible
window.QuickAccountMappingDialog = QuickAccountMappingDialog;

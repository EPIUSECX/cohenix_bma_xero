frappe.pages['xero-sync-dashboard'].on_page_load = function(wrapper) {
    var page = frappe.ui.make_app_page({
        parent: wrapper,
        title: 'Xero Sync Dashboard',
        single_column: true
    });

    // Initialize dashboard
    let dashboard = new XeroSyncDashboard(page);
    dashboard.init();
    
    // Make dashboard globally accessible
    window.dashboard = dashboard;
};

class XeroSyncDashboard {
    constructor(page) {
        this.page = page;
        this.wrapper = page.main;
        this.current_tab = 'overview';
        this.refresh_interval = null;
        this.auto_refresh = true;
        this.logs_start = 0;
        this.logs_filters = {};
    }

    init() {
        this.setup_page_actions();
        this.render_layout();
        this.setup_tabs();
        this.load_overview();
        this.start_auto_refresh();
    }

    setup_page_actions() {
        // Primary actions
        this.page.set_primary_action("Refresh", () => {
            this.refresh_current_tab();
        }, "refresh");

        // Secondary actions
        this.page.add_action_item("Settings", () => {
            frappe.set_route('Form', 'Xero Settings');
        });

        this.page.add_action_item("Toggle Auto-refresh", () => {
            this.toggle_auto_refresh();
        });

        this.page.add_action_item("Export Logs", () => {
            this.export_logs();
        });
    }

    render_layout() {
        // Add Cohenix HR theme CSS
        $(`<style>
            /* ============================================================
               XERO SYNC DASHBOARD — Cohenix HR Theme
               Injected by render_layout() in xero_sync_dashboard.js
               ============================================================ */

            :root {
                --ch-primary:          #3B5BDB;
                --ch-primary-dark:     #2F4AC0;
                --ch-primary-light:    #EDF2FF;
                --ch-accent:           #4DABF7;
                --ch-success:          #2F9E44;
                --ch-success-bg:       #EBFBEE;
                --ch-warning:          #E67700;
                --ch-warning-bg:       #FFF9DB;
                --ch-danger:           #C92A2A;
                --ch-danger-bg:        #FFF5F5;
                --ch-info:             #1971C2;
                --ch-info-bg:          #E7F5FF;
                --ch-bg:               #F8F9FA;
                --ch-surface:          #FFFFFF;
                --ch-border:           #E9ECEF;
                --ch-text:             #1A1A2E;
                --ch-text-muted:       #868E96;
                --ch-shadow-sm:        0 1px 4px rgba(0,0,0,0.06);
                --ch-shadow-md:        0 2px 8px rgba(0,0,0,0.08);
                --ch-shadow-hover:     0 4px 16px rgba(59,91,219,0.12);
                --ch-radius-sm:        6px;
                --ch-radius-md:        10px;
                --ch-radius-lg:        12px;
                --ch-radius-pill:      999px;
            }

            /* Dark mode support */
            html[data-theme-mode="dark"] {
                --ch-bg:               #1A1D23;
                --ch-surface:          #242830;
                --ch-border:           #2E3340;
                --ch-text:             #E9ECEF;
                --ch-text-muted:       #868E96;
                --ch-primary-light:    #1E2A5E;
                --ch-success-bg:       #1A2E20;
                --ch-warning-bg:       #2E2000;
                --ch-danger-bg:        #2E1A1A;
                --ch-info-bg:          #1A2540;
            }

            /* ─── Page Container ─── */
            .xero-dashboard-container {
                padding: 24px;
                background: var(--ch-bg);
                min-height: calc(100vh - 150px);
                color: var(--ch-text);
                font-family: -apple-system, BlinkMacSystemFont, 'Inter', 'Segoe UI', sans-serif;
            }

            /* ─── Tab Navigation (pill style) ─── */
            .xero-dashboard-tabs {
                display: flex;
                justify-content: center;
                margin-bottom: 24px;
            }

            .xero-dashboard-container .nav-tabs {
                display: flex;
                flex-wrap: wrap;
                gap: 8px;
                border: none;
                padding: 0;
                background: transparent;
                justify-content: center;
            }

            .xero-dashboard-container .nav-tabs .nav-link {
                color: var(--ch-text-muted);
                background: var(--ch-surface);
                border: 1px solid var(--ch-border);
                border-radius: var(--ch-radius-pill);
                padding: 7px 18px;
                font-size: 13px;
                font-weight: 500;
                line-height: 1.4;
                transition: border-color 0.15s, background 0.15s, color 0.15s;
                white-space: nowrap;
            }

            .xero-dashboard-container .nav-tabs .nav-link:hover:not(.active) {
                background: var(--ch-primary-light);
                border-color: var(--ch-primary);
                color: var(--ch-primary);
                text-decoration: none;
            }

            .xero-dashboard-container .nav-tabs .nav-link.active {
                background: var(--ch-primary) !important;
                border-color: var(--ch-primary) !important;
                color: #fff !important;
                box-shadow: var(--ch-shadow-md);
            }

            /* ─── Content Wrapper ─── */
            .xero-dashboard-content {
                background: transparent;
                border: none;
                border-radius: 0;
                padding: 0;
                min-height: 500px;
            }

            .tab-content { display: none; }
            .tab-content.active { display: block; }

            /* ─── Cards ─── */
            .metric-card, .entity-card, .card, .xero-card {
                background: var(--ch-surface);
                border: 1px solid var(--ch-border);
                border-radius: var(--ch-radius-lg);
                box-shadow: var(--ch-shadow-sm);
                margin-bottom: 20px;
                overflow: hidden;
                transition: box-shadow 0.2s;
            }

            .metric-card:hover, .entity-card:hover {
                box-shadow: var(--ch-shadow-hover);
            }

            .card-header {
                background: var(--ch-surface);
                border-bottom: 1px solid var(--ch-border);
                padding: 16px 20px;
                font-size: 13px;
                font-weight: 600;
                color: var(--ch-text);
                display: flex;
                align-items: center;
                gap: 8px;
            }

            .card-header i {
                color: var(--ch-primary);
                font-size: 14px;
            }

            .card-body {
                background: var(--ch-surface);
                padding: 20px 24px;
                color: var(--ch-text);
            }

            /* ─── Stat / Metric Values ─── */
            .stat-value, .frappe-card-value {
                font-size: 28px;
                font-weight: 700;
                color: var(--ch-text);
                line-height: 1.2;
            }

            .stat-label, .frappe-card-title {
                font-size: 11px;
                font-weight: 500;
                letter-spacing: 0.06em;
                text-transform: uppercase;
                color: var(--ch-text-muted);
                margin-top: 4px;
            }

            /* Overview 4-stat grid */
            .overview-stats-grid {
                display: grid;
                grid-template-columns: repeat(4, 1fr);
                gap: 16px;
                margin-bottom: 24px;
            }

            .overview-stat-card {
                background: var(--ch-surface);
                border: 1px solid var(--ch-border);
                border-radius: var(--ch-radius-lg);
                padding: 20px 24px;
                box-shadow: var(--ch-shadow-sm);
                text-align: center;
            }

            .overview-stat-card .stat-icon {
                font-size: 22px;
                margin-bottom: 8px;
            }

            .overview-stat-card .stat-value {
                font-size: 32px;
                font-weight: 700;
                color: var(--ch-text);
            }

            .overview-stat-card .stat-label {
                color: var(--ch-text-muted);
            }

            /* ─── Status Badges ─── */
            .badge, span.badge {
                display: inline-flex;
                align-items: center;
                padding: 3px 10px;
                border-radius: var(--ch-radius-pill);
                font-size: 11px;
                font-weight: 600;
                letter-spacing: 0.03em;
                text-transform: capitalize;
                line-height: 1.6;
            }

            .badge-success, .badge.success, span.indicator-pill.green {
                background: var(--ch-success-bg) !important;
                color: var(--ch-success) !important;
            }

            .badge-danger, .badge.error, span.indicator-pill.red {
                background: var(--ch-danger-bg) !important;
                color: var(--ch-danger) !important;
            }

            .badge-warning, .badge.warning, span.indicator-pill.orange {
                background: var(--ch-warning-bg) !important;
                color: var(--ch-warning) !important;
            }

            .badge-info, .badge.info, span.indicator-pill.blue {
                background: var(--ch-info-bg) !important;
                color: var(--ch-info) !important;
            }

            .badge-primary {
                background: var(--ch-primary-light) !important;
                color: var(--ch-primary) !important;
            }

            .badge-secondary {
                background: var(--ch-border) !important;
                color: var(--ch-text-muted) !important;
            }

            .badge-light {
                background: var(--ch-bg) !important;
                color: var(--ch-text) !important;
            }

            /* ─── Tables ─── */
            .table {
                color: var(--ch-text);
                border-collapse: collapse;
                width: 100%;
                font-size: 13px;
            }

            .table thead th {
                background: var(--ch-bg);
                color: var(--ch-text-muted);
                font-size: 11px;
                font-weight: 600;
                letter-spacing: 0.06em;
                text-transform: uppercase;
                border-bottom: 1px solid var(--ch-border);
                border-top: none;
                padding: 10px 12px;
            }

            .table tbody td {
                border-top: 1px solid var(--ch-border);
                padding: 10px 12px;
                color: var(--ch-text);
                vertical-align: middle;
            }

            .table tbody tr:hover td {
                background: var(--ch-primary-light);
            }

            .table-danger td { background: var(--ch-danger-bg) !important; }
            .table-success td { background: var(--ch-success-bg) !important; }

            /* Progress bars */
            .progress {
                height: 6px;
                border-radius: var(--ch-radius-pill);
                background: var(--ch-border);
                overflow: hidden;
            }

            .progress-bar {
                background: var(--ch-primary);
                border-radius: var(--ch-radius-pill);
                transition: width 0.4s ease;
            }

            .progress-bar.bg-success { background: var(--ch-success) !important; }
            .progress-bar.bg-danger  { background: var(--ch-danger)  !important; }
            .progress-bar.bg-warning { background: var(--ch-warning) !important; }

            /* ─── Buttons ─── */
            .btn-primary {
                background: var(--ch-primary) !important;
                border-color: var(--ch-primary) !important;
                color: #fff !important;
                border-radius: var(--ch-radius-md) !important;
                font-weight: 500;
                font-size: 13px;
                padding: 8px 18px;
            }

            .btn-primary:hover {
                background: var(--ch-primary-dark) !important;
                border-color: var(--ch-primary-dark) !important;
                box-shadow: var(--ch-shadow-md);
            }

            .btn-warning {
                background: var(--ch-warning-bg) !important;
                border-color: var(--ch-warning) !important;
                color: var(--ch-warning) !important;
                border-radius: var(--ch-radius-md) !important;
                font-weight: 500;
            }

            .btn-danger {
                background: var(--ch-danger-bg) !important;
                border-color: var(--ch-danger) !important;
                color: var(--ch-danger) !important;
                border-radius: var(--ch-radius-md) !important;
                font-weight: 500;
            }

            .btn-secondary {
                background: var(--ch-surface) !important;
                border-color: var(--ch-border) !important;
                color: var(--ch-text) !important;
                border-radius: var(--ch-radius-md) !important;
                font-weight: 500;
            }

            .btn-secondary:hover {
                border-color: var(--ch-primary) !important;
                color: var(--ch-primary) !important;
            }

            .btn-info {
                background: var(--ch-info-bg) !important;
                border-color: var(--ch-info) !important;
                color: var(--ch-info) !important;
                border-radius: var(--ch-radius-md) !important;
                font-weight: 500;
            }

            .btn-outline-primary {
                border-color: var(--ch-primary) !important;
                color: var(--ch-primary) !important;
                border-radius: var(--ch-radius-md) !important;
                background: transparent !important;
            }

            .btn-outline-primary:hover {
                background: var(--ch-primary-light) !important;
            }

            /* ─── Error / Log Items ─── */
            .error-item {
                background: var(--ch-surface);
                border: 1px solid var(--ch-border);
                border-left: 3px solid var(--ch-danger);
                border-radius: 0 var(--ch-radius-md) var(--ch-radius-md) 0;
                padding: 14px 16px;
                margin-bottom: 10px;
                font-size: 13px;
            }

            .error-item .error-title {
                font-weight: 600;
                color: var(--ch-text);
                font-size: 13px;
            }

            .error-item .error-meta {
                color: var(--ch-text-muted);
                font-size: 12px;
                margin-top: 2px;
            }

            .job-item {
                background: var(--ch-surface);
                border: 1px solid var(--ch-border);
                border-left: 3px solid var(--ch-primary);
                border-radius: 0 var(--ch-radius-md) var(--ch-radius-md) 0;
                padding: 14px 16px;
                margin-bottom: 10px;
                font-size: 13px;
            }

            /* ─── Manual Sync Operations Header Banner ─── */
            .xero-sync-header {
                background: var(--ch-primary);
                color: #fff;
                padding: 20px 24px;
                border-radius: var(--ch-radius-lg) var(--ch-radius-lg) 0 0;
            }

            .xero-sync-title {
                font-size: 17px;
                font-weight: 700;
                margin: 0;
                color: #fff !important;
                display: flex;
                align-items: center;
                gap: 10px;
            }

            .xero-sync-subtitle {
                font-size: 13px;
                color: rgba(255,255,255,0.85) !important;
                margin: 6px 0 0 0;
            }

            .xero-sync-status {
                background: rgba(255,255,255,0.2);
                border: 1px solid rgba(255,255,255,0.3);
                color: #fff;
                padding: 4px 12px;
                border-radius: var(--ch-radius-pill);
                font-size: 12px;
                font-weight: 500;
                position: absolute;
                top: 20px;
                right: 24px;
            }

            .xero-sync-body {
                background: var(--ch-surface);
                padding: 28px 24px;
                border-radius: 0 0 var(--ch-radius-lg) var(--ch-radius-lg);
                border: 1px solid var(--ch-border);
                border-top: none;
            }

            .sync-direction-section {
                margin-bottom: 40px;
            }

            .sync-direction-section.disabled-section {
                opacity: 0.6;
                pointer-events: none;
                position: relative;
            }

            .sync-direction-section.disabled-section::after {
                content: '';
                position: absolute;
                top: 0; left: 0; right: 0; bottom: 0;
                background: rgba(128,128,128,0.1);
                border-radius: var(--ch-radius-md);
                z-index: 1;
            }

            /* ─── Sync Button Grid ─── */
            .sync-direction-header {
                display: flex;
                align-items: center;
                gap: 14px;
                padding-bottom: 14px;
                border-bottom: 1px solid var(--ch-border);
                margin-bottom: 20px;
            }

            .sync-direction-icon {
                width: 38px;
                height: 38px;
                border-radius: var(--ch-radius-md);
                display: flex;
                align-items: center;
                justify-content: center;
                font-size: 16px;
                color: #fff;
                flex-shrink: 0;
            }

            .sync-direction-icon.to-xero   { background: var(--ch-primary); }
            .sync-direction-icon.from-xero { background: var(--ch-success); }

            .sync-direction-info h3 {
                margin: 0;
                font-size: 15px;
                font-weight: 600;
                color: var(--ch-text);
            }

            .sync-direction-info p {
                margin: 3px 0 0 0;
                font-size: 12px;
                color: var(--ch-text-muted);
            }

            .sync-buttons-grid {
                display: grid;
                grid-template-columns: repeat(auto-fill, minmax(230px, 1fr));
                gap: 12px;
            }

            .xero-sync-button {
                display: flex;
                align-items: center;
                gap: 14px;
                padding: 14px 16px;
                background: var(--ch-surface);
                border: 1px solid var(--ch-border);
                border-radius: var(--ch-radius-md);
                cursor: pointer;
                transition: border-color 0.15s, box-shadow 0.15s, background 0.15s;
                text-decoration: none !important;
                color: var(--ch-text) !important;
            }

            .xero-sync-button:hover {
                border-color: var(--ch-primary);
                box-shadow: var(--ch-shadow-hover);
                background: var(--ch-primary-light);
            }

            .xero-sync-button:active {
                transform: translateY(1px);
            }

            .sync-button-icon {
                width: 34px;
                height: 34px;
                border-radius: var(--ch-radius-sm);
                display: flex;
                align-items: center;
                justify-content: center;
                font-size: 16px;
                color: #fff !important;
                flex-shrink: 0;
            }

            .sync-button-icon i {
                color: #fff !important;
                font-size: 15px !important;
                font-weight: 900 !important;
            }

            .sync-button-text { flex: 1; }

            .sync-button-title {
                font-size: 13px;
                font-weight: 600;
                color: var(--ch-text);
            }

            /* Icon color palette — entity-specific */
            .icon-sales-invoice      { background: #3B5BDB; }
            .icon-purchase-invoice   { background: #1971C2; }
            .icon-payment-entry      { background: #2F9E44; }
            .icon-journal-entry      { background: #E67700; }
            .icon-customer           { background: #7048E8; }
            .icon-supplier           { background: #D9480F; }
            .icon-item               { background: #0C8599; }
            .icon-quotation          { background: #9C36B5; }
            .icon-bank-transaction   { background: #495057; }
            .icon-sync-accounts      { background: #2F9E44; }
            .icon-sync-contacts      { background: #1971C2; }
            .icon-sync-items         { background: #0C8599; }
            .icon-sync-invoices      { background: #3B5BDB; }
            .icon-sync-credit-notes  { background: #C92A2A; }
            .icon-sync-payments      { background: #2F9E44; }
            .icon-sync-bank-transactions { background: #495057; }
            .icon-sync-quotes        { background: #9C36B5; }
            .icon-sync-purchase-orders   { background: #D9480F; }
            .icon-sync-manual-journals   { background: #E67700; }

            /* ─── Bulk Operations ─── */
            .bulk-operations-row {
                display: flex;
                gap: 12px;
                flex-wrap: wrap;
            }

            .bulk-operations-row .btn {
                flex: 1;
                min-width: 160px;
                border-radius: var(--ch-radius-md);
                font-weight: 500;
                padding: 10px 20px;
                font-size: 13px;
            }

            /* ─── Entity Status Grid ─── */
            .entity-status-grid {
                display: grid;
                grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
                gap: 16px;
            }

            .entity-card {
                background: var(--ch-surface);
                border: 1px solid var(--ch-border);
                border-radius: var(--ch-radius-lg);
                padding: 18px 20px;
                box-shadow: var(--ch-shadow-sm);
                transition: box-shadow 0.2s;
                margin-bottom: 0;
            }

            .entity-card:hover {
                box-shadow: var(--ch-shadow-hover);
            }

            .entity-card-header {
                display: flex;
                align-items: center;
                justify-content: space-between;
                margin-bottom: 14px;
            }

            .entity-card-title {
                font-size: 13px;
                font-weight: 600;
                color: var(--ch-text);
            }

            .entity-count-badge {
                background: var(--ch-primary-light);
                color: var(--ch-primary);
                border-radius: var(--ch-radius-pill);
                font-size: 11px;
                font-weight: 700;
                padding: 2px 9px;
            }

            .entity-stats-row {
                display: flex;
                justify-content: space-between;
                text-align: center;
                margin-bottom: 12px;
            }

            .entity-stat { flex: 1; }

            .entity-stat-value {
                font-size: 20px;
                font-weight: 700;
                line-height: 1.2;
            }

            .entity-stat-label {
                font-size: 10px;
                text-transform: uppercase;
                letter-spacing: 0.06em;
                color: var(--ch-text-muted);
                margin-top: 2px;
            }

            .entity-stat.synced  .entity-stat-value { color: var(--ch-success); }
            .entity-stat.pending .entity-stat-value { color: var(--ch-warning); }
            .entity-stat.errors  .entity-stat-value { color: var(--ch-danger); }

            .entity-card-footer {
                display: flex;
                align-items: center;
                justify-content: space-between;
                margin-top: 12px;
                padding-top: 10px;
                border-top: 1px solid var(--ch-border);
                font-size: 12px;
                color: var(--ch-text-muted);
            }

            .entity-sync-now-btn {
                background: none;
                border: none;
                color: var(--ch-primary);
                font-size: 12px;
                font-weight: 600;
                cursor: pointer;
                padding: 0;
                text-decoration: none;
            }

            .entity-sync-now-btn:hover {
                color: var(--ch-primary-dark);
                text-decoration: underline;
            }

            /* ─── Last Sync Attempts ─── */
            .sync-attempt-block {
                background: var(--ch-surface);
                border: 1px solid var(--ch-border);
                border-radius: var(--ch-radius-lg);
                margin-bottom: 16px;
                overflow: hidden;
                box-shadow: var(--ch-shadow-sm);
            }

            .sync-attempt-header {
                display: flex;
                align-items: center;
                justify-content: space-between;
                padding: 14px 20px;
                cursor: pointer;
                font-weight: 600;
                font-size: 13px;
                color: #fff;
            }

            .sync-attempt-header.status-failed   { background: var(--ch-danger); }
            .sync-attempt-header.status-success  { background: var(--ch-success); }
            .sync-attempt-header.status-partial  { background: var(--ch-warning); }
            .sync-attempt-header.status-warnings { background: #F59F00; }
            .sync-attempt-header.status-info     { background: var(--ch-info); }

            .sync-attempt-body { padding: 16px 20px; }

            /* ─── Sync Logs ─── */
            .sync-logs-filters {
                display: flex;
                gap: 10px;
                align-items: center;
                flex-wrap: wrap;
                padding: 0 0 16px 0;
                border-bottom: 1px solid var(--ch-border);
                margin-bottom: 16px;
            }

            .sync-logs-filters select,
            .sync-logs-filters input {
                border: 1px solid var(--ch-border);
                border-radius: var(--ch-radius-md);
                padding: 7px 12px;
                font-size: 13px;
                color: var(--ch-text);
                background: var(--ch-surface);
            }

            .sync-logs-filters select:focus,
            .sync-logs-filters input:focus {
                outline: none;
                border-color: var(--ch-primary);
                box-shadow: 0 0 0 3px var(--ch-primary-light);
            }

            /* ─── Loading Overlay ─── */
            .xero-loading-overlay {
                position: absolute;
                inset: 0;
                background: var(--ch-surface);
                opacity: 0.95;
                display: flex;
                align-items: center;
                justify-content: center;
                z-index: 1000;
                border-radius: var(--ch-radius-lg);
            }

            .loading-content {
                text-align: center;
                color: var(--ch-text);
            }

            /* ─── Overview Connection Banner ─── */
            .xero-connection-banner {
                background: var(--ch-surface);
                border: 1px solid var(--ch-border);
                border-radius: var(--ch-radius-lg);
                padding: 20px 24px;
                margin-bottom: 20px;
                box-shadow: var(--ch-shadow-sm);
                display: flex;
                align-items: center;
                justify-content: space-between;
                flex-wrap: wrap;
                gap: 16px;
            }

            .xero-connection-title {
                font-size: 15px;
                font-weight: 600;
                color: var(--ch-text);
                display: flex;
                align-items: center;
                gap: 8px;
            }

            .xero-connection-meta {
                display: flex;
                gap: 32px;
                flex-wrap: wrap;
            }

            .xero-connection-meta-item label {
                font-size: 11px;
                text-transform: uppercase;
                letter-spacing: 0.06em;
                color: var(--ch-text-muted);
                display: block;
                margin-bottom: 2px;
                font-weight: 500;
            }

            .xero-connection-meta-item span {
                font-size: 13px;
                font-weight: 600;
                color: var(--ch-text);
            }

            /* ─── Analytics ─── */
            .analytics-section-title {
                font-size: 13px;
                font-weight: 600;
                color: var(--ch-text);
                margin-bottom: 14px;
                padding-bottom: 8px;
                border-bottom: 1px solid var(--ch-border);
            }

            /* ─── Utility: text colors ─── */
            .text-primary { color: var(--ch-primary) !important; }
            .text-success { color: var(--ch-success) !important; }
            .text-warning { color: var(--ch-warning) !important; }
            .text-danger  { color: var(--ch-danger)  !important; }
            .text-info    { color: var(--ch-info)    !important; }
            .text-muted   { color: var(--ch-text-muted) !important; }

            /* ─── Utility: background colors ─── */
            .bg-primary { background: var(--ch-primary)    !important; }
            .bg-success { background: var(--ch-success)    !important; }
            .bg-warning { background: var(--ch-warning)    !important; }
            .bg-danger  { background: var(--ch-danger)     !important; }
            .bg-info    { background: var(--ch-info)       !important; }
        </style>`).appendTo('head');

        this.wrapper.html(`
            <div class="xero-dashboard-container">
                <!-- Navigation Tabs -->
                <div class="xero-dashboard-tabs">
                    <ul class="nav nav-tabs" role="tablist">
                        <li class="nav-item">
                            <a class="nav-link active" data-tab="overview" href="#overview">
                                <i class="fa fa-dashboard"></i> Overview
                            </a>
                        </li>
                        <li class="nav-item">
                            <a class="nav-link" data-tab="sync-ops" href="#sync-ops">
                                <i class="fa fa-sync"></i> Manual Sync Operations
                            </a>
                        </li>
                        <li class="nav-item">
                            <a class="nav-link" data-tab="last-sync" href="#last-sync">
                                <i class="fa fa-history"></i> Last Sync Attempts
                            </a>
                        </li>
                        <li class="nav-item">
                            <a class="nav-link" data-tab="logs" href="#logs">
                                <i class="fa fa-list"></i> Sync Logs
                            </a>
                        </li>
                        <li class="nav-item">
                            <a class="nav-link" data-tab="analytics" href="#analytics">
                                <i class="fa fa-chart-line"></i> Analytics
                            </a>
                        </li>
                        <li class="nav-item">
                            <a class="nav-link" data-tab="entities" href="#entities">
                                <i class="fa fa-database"></i> Entity Status
                            </a>
                        </li>
                    </ul>
                </div>

                <!-- Tab Content -->
                <div class="xero-dashboard-content" style="position: relative;">
                    <div id="overview" class="tab-content active"></div>
                    <div id="sync-ops" class="tab-content"></div>
                    <div id="last-sync" class="tab-content"></div>
                    <div id="logs" class="tab-content"></div>
                    <div id="analytics" class="tab-content"></div>
                    <div id="entities" class="tab-content"></div>
                    
                    <!-- Loading Overlay -->
                    <div class="xero-loading-overlay" style="display: none;">
                        <div class="loading-content">
                            <div class="spinner-border text-primary" role="status"></div>
                            <p class="mt-2">Loading...</p>
                        </div>
                    </div>
                </div>
            </div>
        `);
    }

    setup_tabs() {
        $(this.wrapper).find('.nav-link').on('click', (e) => {
            e.preventDefault();
            const tab = $(e.target).closest('.nav-link').data('tab');
            this.switch_tab(tab);
        });
    }

    switch_tab(tab) {
        // Update active tab
        $(this.wrapper).find('.nav-link').removeClass('active');
        $(this.wrapper).find(`[data-tab="${tab}"]`).addClass('active');
        
        // Update content
        $(this.wrapper).find('.tab-content').removeClass('active');
        $(this.wrapper).find(`#${tab}`).addClass('active');
        
        this.current_tab = tab;
        
        // Load tab content
        switch(tab) {
            case 'overview':
                this.load_overview();
                break;
            case 'sync-ops':
                this.load_sync_operations();
                break;
            case 'last-sync':
                this.load_last_sync_attempts();
                break;
            case 'logs':
                this.load_logs();
                break;
            case 'analytics':
                this.load_analytics();
                break;
            case 'entities':
                this.load_entity_status();
                break;
        }
    }

    show_loading() {
        $(this.wrapper).find('.xero-loading-overlay').show();
    }

    hide_loading() {
        $(this.wrapper).find('.xero-loading-overlay').hide();
    }

    load_overview() {
        this.show_loading();
        frappe.call({
            method: 'xero.xero.page.xero_sync_dashboard.xero_sync_dashboard.get_dashboard_overview',
            callback: (r) => {
                this.hide_loading();
                if (r.message && !r.message.error) {
                    this.render_overview(r.message);
                } else {
                    this.show_error('Failed to load dashboard overview', r.message?.error);
                }
            }
        });
    }

    render_overview(data) {
        const overview_html = `
            <!-- Connection Banner -->
            <div class="xero-connection-banner">
                <div class="xero-connection-title">
                    <img src="/assets/xero/Xero_software_logo.svg" alt="Xero" style="height:22px;width:auto;vertical-align:middle;">
                    Xero Connection
                    <span class="badge badge-${data.connection.connected ? 'success' : 'danger'}" style="margin-left:6px;">
                        ${data.connection.connected ? 'Connected' : 'Disconnected'}
                    </span>
                </div>
                <div class="xero-connection-meta">
                    <div class="xero-connection-meta-item">
                        <label>Tenant</label>
                        <span>${data.connection.tenant_name || '—'}</span>
                    </div>
                    <div class="xero-connection-meta-item">
                        <label>Sync Enabled</label>
                        <span class="badge badge-${data.connection.sync_enabled ? 'success' : 'warning'}">
                            ${data.connection.sync_enabled ? 'Yes' : 'No'}
                        </span>
                    </div>
                    <div class="xero-connection-meta-item">
                        <label>Last Sync</label>
                        <span>${data.connection.last_sync ? frappe.datetime.comment_when(data.connection.last_sync) : 'Never'}</span>
                    </div>
                    <div class="xero-connection-meta-item">
                        <label>Health Score</label>
                        <span>${data.health.score}%</span>
                    </div>
                </div>
            </div>

            <!-- Key Metrics Grid -->
            <div class="overview-stats-grid">
                <div class="overview-stat-card">
                    <div class="stat-icon text-success"><i class="fa fa-check-circle"></i></div>
                    <div class="stat-value">${data.sync_stats.overall.find(s => s.status === 'Success')?.count || 0}</div>
                    <div class="stat-label">Successful Syncs (24h)</div>
                </div>
                <div class="overview-stat-card">
                    <div class="stat-icon text-danger"><i class="fa fa-exclamation-circle"></i></div>
                    <div class="stat-value">${data.sync_stats.overall.find(s => s.status === 'Error')?.count || 0}</div>
                    <div class="stat-label">Failed Syncs (24h)</div>
                </div>
                <div class="overview-stat-card">
                    <div class="stat-icon text-info"><i class="fa fa-clock"></i></div>
                    <div class="stat-value">${data.active_jobs.length}</div>
                    <div class="stat-label">Active Jobs</div>
                </div>
                <div class="overview-stat-card">
                    <div class="stat-icon text-primary"><i class="fa fa-database"></i></div>
                    <div class="stat-value">${data.entity_status.reduce((sum, e) => sum + e.synced, 0)}</div>
                    <div class="stat-label">Total Synced Entities</div>
                </div>
            </div>

            <!-- Recent Errors & Active Jobs -->
            <div class="row">
                <div class="col-md-6">
                    <div class="card">
                        <div class="card-header">
                            <i class="fa fa-exclamation-triangle"></i> Recent Errors
                        </div>
                        <div class="card-body">
                            ${data.recent_errors.errors.length > 0 ?
                                data.recent_errors.errors.slice(0, 5).map(error => `
                                    <div class="error-item">
                                        <div class="d-flex justify-content-between align-items-start">
                                            <span class="error-title">${error.erpnext_doc_type} ${error.erpnext_doc_name}</span>
                                            <small class="text-muted" style="white-space:nowrap;margin-left:8px;">${frappe.datetime.comment_when(error.timestamp)}</small>
                                        </div>
                                        <div class="error-meta">${error.message}</div>
                                        <span class="badge badge-secondary" style="margin-top:4px;">${error.category}</span>
                                    </div>
                                `).join('') :
                                '<p class="text-muted" style="margin:0;">No recent errors</p>'
                            }
                        </div>
                    </div>
                </div>
                <div class="col-md-6">
                    <div class="card">
                        <div class="card-header">
                            <i class="fa fa-tasks"></i> Active Jobs
                        </div>
                        <div class="card-body">
                            ${data.active_jobs.length > 0 ?
                                data.active_jobs.slice(0, 5).map(job => `
                                    <div class="job-item">
                                        <div class="d-flex justify-content-between align-items-center">
                                            <strong style="font-size:13px;">${job.job_name}</strong>
                                            <span class="badge badge-${this.get_job_status_color(job.status)}">${job.status}</span>
                                        </div>
                                        <div class="error-meta">
                                            Started: ${frappe.datetime.comment_when(job.started_at || job.creation)}
                                            ${job.duration ? `· ${Math.round(job.duration / 60)} min` : ''}
                                        </div>
                                    </div>
                                `).join('') :
                                '<p class="text-muted" style="margin:0;">No active jobs</p>'
                            }
                        </div>
                    </div>
                </div>
            </div>
        `;

        $(this.wrapper).find('#overview').html(overview_html);
    }

    load_sync_operations() {
        // Fetch settings first to determine which sections to show
        frappe.call({
            method: 'xero.xero.page.xero_sync_dashboard.xero_sync_dashboard.get_dashboard_overview',
            callback: (r) => {
                if (r.message && !r.message.error) {
                    this.render_sync_operations(r.message.connection);
                } else {
                    this.show_error('Failed to load sync operations', r.message?.error);
                }
            }
        });
    }

    render_sync_operations(connection_status) {
        const sync_to_xero_enabled = connection_status.sync_to_xero_enabled;
        const sync_from_xero_enabled = connection_status.sync_from_xero_enabled;
        
        const sync_ops_html = `
            <div class="row">
                <!-- Professional Manual Sync Operations -->
                <div class="col-md-12 mb-4">
                    <div class="card">
                        <div class="xero-sync-header">
                            <h2 class="xero-sync-title">
                                <i class="fa fa-sync-alt"></i>
                                Manual Sync Operations
                            </h2>
                            <p class="xero-sync-subtitle">
                                Trigger synchronization between ERPNext and Xero for specific entity types
                            </p>
                            <div class="xero-sync-status">
                                <i class="fa fa-circle text-success"></i> Ready
                            </div>
                        </div>
                        <div class="xero-sync-body">
                            <!-- ERPNext to Xero Section -->
                            <div class="sync-direction-section ${!sync_to_xero_enabled ? 'disabled-section' : ''}">
                                ${!sync_to_xero_enabled ? `
                                    <div class="alert alert-warning mb-3">
                                        <h5><i class="fa fa-exclamation-triangle"></i> Sync TO Xero is Disabled</h5>
                                        <p class="mb-2">Outbound sync from ERPNext to Xero is currently disabled. No data will be written to Xero.</p>
                                        <p class="mb-0">
                                            <strong>To enable:</strong> Go to
                                            <a href="/app/xero-settings" target="_blank">Xero Settings</a>
                                            and check "Enable Sync TO Xero (ERPNext → Xero)"
                                        </p>
                                    </div>
                                ` : ''}
                                <div class="sync-direction-header">
                                    <div class="sync-direction-icon to-xero">
                                        <i class="fa fa-arrow-right"></i>
                                    </div>
                                    <div class="sync-direction-info">
                                        <h3>ERPNext → Xero</h3>
                                        <p>Push data from ERPNext to Xero</p>
                                    </div>
                                </div>
                                <div class="sync-buttons-grid">
                                    ${this.render_xero_sync_buttons([
                                        { name: 'Sales Invoice', icon: 'fa-file-text', class: 'icon-sales-invoice' },
                                        { name: 'Purchase Invoice', icon: 'fa-file', class: 'icon-purchase-invoice' },
                                        { name: 'Payment Entry', icon: 'fa-credit-card', class: 'icon-payment-entry' },
                                        { name: 'Journal Entry', icon: 'fa-book', class: 'icon-journal-entry' },
                                        { name: 'Customer', icon: 'fa-user', class: 'icon-customer' },
                                        { name: 'Supplier', icon: 'fa-truck', class: 'icon-supplier' },
                                        { name: 'Item', icon: 'fa-cube', class: 'icon-item' },
                                        { name: 'Quotation', icon: 'fa-quote-right', class: 'icon-quotation' },
                                        { name: 'Bank Transaction', icon: 'fa-bank', class: 'icon-bank-transaction' }
                                    ], sync_to_xero_enabled)}
                                </div>
                            </div>

                            <!-- Xero to ERPNext Section -->
                            <div class="sync-direction-section ${!sync_from_xero_enabled ? 'disabled-section' : ''}">
                                ${!sync_from_xero_enabled ? `
                                    <div class="alert alert-warning mb-3">
                                        <h5><i class="fa fa-exclamation-triangle"></i> Sync FROM Xero is Disabled</h5>
                                        <p class="mb-2">Inbound sync from Xero to ERPNext is currently disabled. No data will be read from Xero.</p>
                                        <p class="mb-0">
                                            <strong>To enable:</strong> Go to
                                            <a href="/app/xero-settings" target="_blank">Xero Settings</a>
                                            and check "Enable Sync FROM Xero (Xero → ERPNext)"
                                        </p>
                                    </div>
                                ` : ''}
                                <div class="sync-direction-header">
                                    <div class="sync-direction-icon from-xero">
                                        <i class="fa fa-arrow-left"></i>
                                    </div>
                                    <div class="sync-direction-info">
                                        <h3>Xero → ERPNext</h3>
                                        <p>Pull data from Xero to ERPNext</p>
                                    </div>
                                </div>
                                <div class="sync-buttons-grid">
                                    ${this.render_xero_sync_buttons([
                                        { name: 'Xero Contacts', icon: 'fa-users', class: 'icon-sync-contacts' },
                                        { name: 'Xero Accounts', icon: 'fa-list', class: 'icon-sync-accounts' },
                                        { name: 'Xero Items', icon: 'fa-cubes', class: 'icon-sync-items' },
                                        { name: 'Xero Invoices', icon: 'fa-file-text', class: 'icon-sync-invoices' },
                                        { name: 'Xero Credit Notes', icon: 'fa-file', class: 'icon-sync-credit-notes' },
                                        { name: 'Xero Payments', icon: 'fa-credit-card', class: 'icon-sync-payments' },
                                        { name: 'Xero Manual Journals', icon: 'fa-book', class: 'icon-sync-manual-journals' },
                                        { name: 'Xero Quotes', icon: 'fa-quote-left', class: 'icon-sync-quotes' },
                                        { name: 'Xero Bank Transactions', icon: 'fa-bank', class: 'icon-sync-bank-transactions' },
                                        { name: 'Xero Purchase Orders', icon: 'fa-shopping-bag', class: 'icon-sync-purchase-orders' }
                                    ], sync_from_xero_enabled)}
                                </div>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Bulk Operations -->
                <div class="col-md-12 mb-4">
                    <div class="card">
                        <div class="card-header">
                            <i class="fa fa-tasks"></i> Bulk Operations
                        </div>
                        <div class="card-body">
                            <div class="bulk-operations-row">
                                <button class="btn btn-warning" onclick="dashboard.bulk_retry_failed()">
                                    <i class="fa fa-redo"></i> Retry All Failed Jobs
                                </button>
                                <button class="btn btn-primary" onclick="dashboard.sync_all_entities()">
                                    <i class="fa fa-sync-alt"></i> Sync All Entities
                                </button>
                                <button class="btn btn-secondary" onclick="dashboard.clear_old_logs()">
                                    <i class="fa fa-trash"></i> Clear Old Logs
                                </button>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Sync Queue Status -->
                <div class="col-md-12">
                    <div class="card">
                        <div class="card-header">
                            <h5 class="mb-0"><i class="fa fa-list"></i> Sync Queue Status</h5>
                        </div>
                        <div class="card-body">
                            <div id="queue-status">Loading queue status...</div>
                        </div>
                    </div>
                </div>
            </div>
        `;

        $(this.wrapper).find('#sync-ops').html(sync_ops_html);
        this.load_queue_status();
    }

    render_sync_buttons(entities) {
        return entities.map(entity => `
            <button class="btn btn-outline-primary btn-sm mb-2 mr-2 sync-btn"
                    data-entity="${entity}" onclick="dashboard.trigger_sync('${entity}')">
                <i class="fa fa-sync"></i> ${entity}
            </button>
        `).join('');
    }

    render_xero_sync_buttons(entities, enabled = true) {
        return entities.map(entity => `
            <button class="xero-sync-button ${!enabled ? 'disabled' : ''}"
                    data-entity="${entity.name}"
                    onclick="${enabled ? `dashboard.trigger_sync('${entity.name}')` : 'return false;'}"
                    ${!enabled ? 'disabled style="opacity: 0.5; cursor: not-allowed;"' : ''}>
                <div class="sync-button-icon ${entity.class}">
                    <i class="fa ${entity.icon}"></i>
                </div>
                <div class="sync-button-text">
                    <div class="sync-button-title">${entity.name}</div>
                </div>
            </button>
        `).join('');
    }

    render_modern_sync_buttons(entities) {
        return entities.map(entity => `
            <div class="modern-sync-btn-wrapper">
                <button class="btn btn-modern-sync btn-outline-${entity.color} mb-3"
                        data-entity="${entity.name}" onclick="dashboard.trigger_sync('${entity.name}')">
                    <div class="sync-btn-content">
                        <div class="sync-btn-icon">
                            <i class="fa ${entity.icon}"></i>
                        </div>
                        <div class="sync-btn-text">
                            <span class="sync-btn-title">${entity.name}</span>
                        </div>
                    </div>
                    <div class="sync-btn-overlay">
                        <i class="fa fa-sync-alt"></i>
                    </div>
                </button>
            </div>
        `).join('');
    }

    load_analytics() {
        this.show_loading();
        frappe.call({
            method: 'xero.xero.page.xero_sync_dashboard.xero_sync_dashboard.get_sync_statistics',
            callback: (r) => {
                this.hide_loading();
                if (r.message) {
                    this.render_analytics(r.message);
                }
            }
        });
    }

    render_analytics(data) {
        const success_rate = this.calculate_success_rate(data.overall);
        const analytics_html = `
            <!-- Performance Metrics -->
            <div class="overview-stats-grid" style="margin-bottom:24px;">
                <div class="overview-stat-card">
                    <div class="stat-value">${data.performance.total_operations || 0}</div>
                    <div class="stat-label">Total Operations</div>
                </div>
                <div class="overview-stat-card">
                    <div class="stat-value">${Math.round(data.performance.avg_processing_time || 0)}s</div>
                    <div class="stat-label">Avg Processing Time</div>
                </div>
                <div class="overview-stat-card">
                    <div class="stat-value">${data.performance.entity_types_synced || 0}</div>
                    <div class="stat-label">Entity Types</div>
                </div>
                <div class="overview-stat-card">
                    <div class="stat-value" style="color:${success_rate < 50 ? 'var(--ch-danger)' : 'var(--ch-text)'};">${success_rate}%</div>
                    <div class="stat-label">Success Rate</div>
                </div>
            </div>

            <!-- Entity Performance -->
            <div class="card">
                <div class="card-header">
                    <i class="fa fa-chart-bar"></i>
                    <span class="analytics-section-title" style="margin:0;padding:0;border:none;">Entity Performance</span>
                </div>
                <div class="card-body" style="padding:0;">
                    <div class="table-responsive">
                        <table class="table">
                            <thead>
                                <tr>
                                    <th>Entity</th>
                                    <th>Total</th>
                                    <th>Success</th>
                                    <th>Errors</th>
                                    <th>Success Rate</th>
                                </tr>
                            </thead>
                            <tbody>
                                ${data.by_entity.map(entity => `
                                    <tr>
                                        <td>${entity.erpnext_doc_type}</td>
                                        <td>${entity.total}</td>
                                        <td class="text-success">${entity.success}</td>
                                        <td class="text-danger">${entity.errors}</td>
                                        <td style="min-width:120px;">
                                            <div class="progress">
                                                <div class="progress-bar bg-success"
                                                     style="width: ${entity.success_rate}%">
                                                </div>
                                            </div>
                                            <small class="text-muted">${Math.round(entity.success_rate)}%</small>
                                        </td>
                                    </tr>
                                `).join('')}
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>
        `;

        $(this.wrapper).find('#analytics').html(analytics_html);
    }

    load_entity_status() {
        this.show_loading();
        frappe.call({
            method: 'xero.xero.page.xero_sync_dashboard.xero_sync_dashboard.get_entity_sync_status',
            callback: (r) => {
                this.hide_loading();
                if (r.message) {
                    this.render_entity_status(r.message);
                }
            }
        });
    }

    render_entity_status(entities) {
        const entity_html = `
            <div class="entity-status-grid">
                ${entities.map(entity => `
                    <div class="entity-card">
                        <div class="entity-card-header">
                            <span class="entity-card-title">${entity.entity}</span>
                            <span class="entity-count-badge">${entity.total}</span>
                        </div>
                        <div class="entity-stats-row">
                            <div class="entity-stat synced">
                                <div class="entity-stat-value">${entity.synced}</div>
                                <div class="entity-stat-label">Synced</div>
                            </div>
                            <div class="entity-stat pending">
                                <div class="entity-stat-value">${entity.pending}</div>
                                <div class="entity-stat-label">Pending</div>
                            </div>
                            <div class="entity-stat errors">
                                <div class="entity-stat-value">${entity.errors}</div>
                                <div class="entity-stat-label">Errors</div>
                            </div>
                        </div>
                        <div class="progress" style="margin-bottom:8px;">
                            <div class="progress-bar bg-success" style="width: ${entity.sync_rate}%"></div>
                        </div>
                        <div class="entity-card-footer">
                            <span>Last sync: ${entity.last_sync ? frappe.datetime.comment_when(entity.last_sync) : 'Never'}</span>
                            <a class="entity-sync-now-btn" onclick="dashboard.trigger_sync('${entity.entity}')">
                                <i class="fa fa-sync"></i> Sync Now
                            </a>
                        </div>
                    </div>
                `).join('')}
            </div>
        `;

        $(this.wrapper).find('#entities').html(entity_html);
    }

    load_logs() {
        const logs_html = `
            <div class="card">
                <div class="card-header">
                    <i class="fa fa-list"></i> Sync Logs
                </div>
                <div class="card-body">
                    <div class="sync-logs-filters">
                        <select id="status-filter">
                            <option value="">All Statuses</option>
                            <option value="Success">Success</option>
                            <option value="Error">Error</option>
                            <option value="Warning">Warning</option>
                            <option value="Info">Info</option>
                        </select>
                        <select id="entity-filter">
                            <option value="">All Entities</option>
                            <option value="Sales Invoice">Sales Invoice</option>
                            <option value="Purchase Invoice">Purchase Invoice</option>
                            <option value="Payment Entry">Payment Entry</option>
                            <option value="Customer">Customer</option>
                            <option value="Supplier">Supplier</option>
                            <option value="Item">Item</option>
                        </select>
                        <input type="text" id="message-filter" placeholder="Search message...">
                        <button class="btn btn-primary btn-sm" onclick="dashboard.apply_log_filters()">
                            <i class="fa fa-filter"></i> Filter
                        </button>
                    </div>
                    <div id="logs-table">Loading logs...</div>
                </div>
            </div>
        `;

        $(this.wrapper).find('#logs').html(logs_html);
        this.load_logs_data();
    }

    load_logs_data(start = 0, filters = {}) {
        frappe.call({
            method: 'xero.xero.page.xero_sync_dashboard.xero_sync_dashboard.get_logs',
            args: {
                start: start,
                page_length: 20,
                filters: filters
            },
            callback: (r) => {
                if (r.message) {
                    this.render_logs_table(r.message);
                }
            }
        });
    }

    render_logs_table(data) {
        const table_html = `
            <div class="table-responsive">
                <table class="table">
                    <thead>
                        <tr>
                            <th>Status</th>
                            <th>Message</th>
                            <th>Document</th>
                            <th>Timestamp</th>
                            <th>Actions</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${data.logs.map(log => `
                            <tr>
                                <td>
                                    <span class="badge badge-${this.get_status_color(log.status)}">
                                        ${log.status}
                                    </span>
                                </td>
                                <td class="text-truncate" style="max-width: 300px;" title="${log.message}">
                                    ${log.message}
                                </td>
                                <td>
                                    ${log.erpnext_doc_type && log.erpnext_doc_name ?
                                        `<a href="/app/${log.erpnext_doc_type.toLowerCase().replace(/ /g, '-')}/${log.erpnext_doc_name}" target="_blank">
                                            ${log.erpnext_doc_type} ${log.erpnext_doc_name}
                                        </a>` :
                                        '<span class="text-muted">-</span>'
                                    }
                                </td>
                                <td>${frappe.datetime.comment_when(log.timestamp)}</td>
                                <td style="white-space:nowrap;">
                                    ${log.status === 'Error' ?
                                        `<a class="text-warning" style="cursor:pointer;margin-right:10px;" data-log-name="${log.name}" onclick="dashboard.retry_job('${log.name}')">
                                            <i class="fa fa-redo"></i> Retry
                                        </a>` :
                                        ''
                                    }
                                    <a class="text-primary" style="cursor:pointer;" onclick="dashboard.view_log_details('${log.name}')">
                                        <i class="fa fa-eye"></i> Details
                                    </a>
                                </td>
                            </tr>
                        `).join('')}
                    </tbody>
                </table>
            </div>

            ${data.has_more ?
                `<div class="text-center mt-3">
                    <button class="btn btn-outline-primary btn-sm" onclick="dashboard.load_more_logs()">
                        Load More
                    </button>
                </div>` :
                ''
            }
        `;

        $(this.wrapper).find('#logs-table').html(table_html);
    }


    // Utility Methods
    get_health_color(score) {
        if (score >= 80) return 'success';
        if (score >= 60) return 'warning';
        return 'danger';
    }

    get_job_status_color(status) {
        const colors = {
            'Queued': 'secondary',
            'Started': 'info',
            'Finished': 'success',
            'Failed': 'danger',
            'Deferred': 'warning'
        };
        return colors[status] || 'secondary';
    }

    get_status_color(status) {
        const colors = {
            'Success': 'success',
            'Error': 'danger',
            'Warning': 'warning',
            'Info': 'info'
        };
        return colors[status] || 'secondary';
    }

    calculate_success_rate(stats) {
        const total = stats.reduce((sum, s) => sum + s.count, 0);
        const success = stats.find(s => s.status === 'Success')?.count || 0;
        return total > 0 ? Math.round((success / total) * 100) : 0;
    }

    // Action Methods
    trigger_sync(entity) {
        frappe.confirm(
            `Are you sure you want to sync all ${entity} records?`,
            () => {
                // Show a sync-in-progress indicator on the button
                const btn = $(this.wrapper).find(`[data-entity="${entity}"]`);
                const original_html = btn.html();
                btn.prop('disabled', true).css('opacity', '0.7');
                btn.find('.sync-button-title').text(`Syncing ${entity}...`);
                
                frappe.call({
                    method: 'xero.xero.page.xero_sync_dashboard.xero_sync_dashboard.trigger_manual_sync',
                    args: { entity_type: entity },
                    callback: (r) => {
                        // Restore button
                        btn.prop('disabled', false).css('opacity', '1');
                        btn.html(original_html);
                        
                        if (r.message && r.message.success) {
                            const batch_id = r.message.sync_batch_id;
                            frappe.show_alert({
                                message: `${entity} sync initiated. Check the "Last Sync Attempts" tab for results.`,
                                indicator: 'green'
                            });
                            
                            // Store the batch ID so we can poll for results
                            if (batch_id) {
                                this._poll_sync_result(entity, batch_id);
                            }
                        } else {
                            frappe.show_alert({
                                message: r.message?.error || 'Sync failed to start',
                                indicator: 'red'
                            });
                        }
                    }
                });
            }
        );
    }

    _poll_sync_result(entity, batch_id) {
        // Poll for sync completion every 5 seconds, up to 2 minutes
        let poll_count = 0;
        const max_polls = 24;
        
        const poll_interval = setInterval(() => {
            poll_count++;
            
            frappe.call({
                method: 'xero.xero.page.xero_sync_dashboard.xero_sync_dashboard.get_sync_batch_status',
                args: { sync_batch_id: batch_id },
                callback: (r) => {
                    if (r.message) {
                        const data = r.message;
                        // Check if sync has produced results (more than just the "started" Info log)
                        if (data.total_logs > 1 || poll_count >= max_polls) {
                            clearInterval(poll_interval);
                            
                            // Show a summary notification
                            if (data.total_logs > 1) {
                                const indicator = data.error_count > 0 ? 'orange' : 'green';
                                let msg = `${entity} sync complete: ${data.success_count} succeeded`;
                                if (data.error_count > 0) msg += `, ${data.error_count} failed`;
                                if (data.warning_count > 0) msg += `, ${data.warning_count} warnings`;
                                
                                frappe.show_alert({
                                    message: msg,
                                    indicator: indicator
                                }, 10);
                            }
                            
                            // Refresh the current tab to show updated data
                            this.refresh_current_tab();
                        }
                    }
                },
                error: () => {
                    // Stop polling on error
                    clearInterval(poll_interval);
                }
            });
        }, 5000);
    }

    bulk_retry_failed() {
        frappe.confirm(
            'Are you sure you want to retry all failed sync jobs?',
            () => {
                frappe.call({
                    method: 'xero.xero.page.xero_sync_dashboard.xero_sync_dashboard.bulk_retry_failed',
                    callback: (r) => {
                        if (r.message && r.message.success) {
                            frappe.show_alert({
                                message: `${r.message.count} jobs queued for retry`,
                                indicator: 'green'
                            });
                            this.refresh_current_tab();
                        }
                    }
                });
            }
        );
    }

    sync_all_entities() {
        frappe.confirm(
            'This will sync all configured entities. This may take a while. Continue?',
            () => {
                frappe.call({
                    method: 'xero.xero.page.xero_sync_dashboard.xero_sync_dashboard.sync_all_entities',
                    callback: (r) => {
                        if (r.message && r.message.success) {
                            frappe.show_alert({
                                message: 'Full sync initiated successfully',
                                indicator: 'green'
                            });
                            this.refresh_current_tab();
                        }
                    }
                });
            }
        );
    }

    clear_old_logs() {
        frappe.prompt([
            {
                label: 'Delete logs older than (days)',
                fieldname: 'days',
                fieldtype: 'Int',
                default: 30,
                reqd: 1
            }
        ], (values) => {
            frappe.call({
                method: 'xero.xero.page.xero_sync_dashboard.xero_sync_dashboard.clear_old_logs',
                args: { days: values.days },
                callback: (r) => {
                    if (r.message && r.message.success) {
                        frappe.show_alert({
                            message: `${r.message.deleted_count} old logs deleted`,
                            indicator: 'green'
                        });
                        this.refresh_current_tab();
                    }
                }
            });
        }, 'Clear Old Logs', 'Clear');
    }

    load_queue_status() {
        frappe.call({
            method: 'xero.xero.page.xero_sync_dashboard.xero_sync_dashboard.get_queue_status',
            callback: (r) => {
                if (r.message) {
                    this.render_queue_status(r.message);
                }
            }
        });
    }

    render_queue_status(data) {
        const queue_html = `
            <div class="table-responsive">
                <table class="table table-sm">
                    <thead>
                        <tr>
                            <th>Queue</th>
                            <th>Pending</th>
                            <th>Running</th>
                            <th>Failed</th>
                            <th>Actions</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${data.queues.map(queue => `
                            <tr>
                                <td>${queue.name}</td>
                                <td><span class="badge badge-warning">${queue.pending}</span></td>
                                <td><span class="badge badge-info">${queue.running}</span></td>
                                <td><span class="badge badge-danger">${queue.failed}</span></td>
                                <td>
                                    <button class="btn btn-xs btn-outline-primary" onclick="dashboard.view_queue('${queue.name}')">
                                        <i class="fa fa-eye"></i> View
                                    </button>
                                </td>
                            </tr>
                        `).join('')}
                    </tbody>
                </table>
            </div>
        `;

        $(this.wrapper).find('#queue-status').html(queue_html);
    }

    apply_log_filters() {
        const status = $(this.wrapper).find('#status-filter').val();
        const entity = $(this.wrapper).find('#entity-filter').val();
        const message = $(this.wrapper).find('#message-filter').val();
        
        this.logs_filters = {};
        if (status) this.logs_filters.status = status;
        if (entity) this.logs_filters.erpnext_doc_type = entity;
        if (message) this.logs_filters.message = message;
        
        this.logs_start = 0;
        this.load_logs_data(0, this.logs_filters);
    }

    load_more_logs() {
        this.logs_start += 20;
        this.load_logs_data(this.logs_start, this.logs_filters);
    }

    view_filtered_logs(filter) {
        // Switch to logs tab
        this.switch_tab('logs');
        
        // Apply filter after a short delay to ensure tab is loaded
        setTimeout(() => {
            // Set filter values in the UI
            if (filter.message) {
                this.logs_filters = {};
                
                // Determine which filter to apply based on the message content
                if (filter.message.includes('account mapping')) {
                    // Show warnings about account mappings
                    this.logs_filters.status = 'Warning';
                    this.logs_filters.message = 'account mapping';
                    $(this.wrapper).find('#status-filter').val('Warning');
                    $(this.wrapper).find('#message-filter').val('account mapping');
                } else if (filter.message.includes('not found in ERPNext')) {
                    // Show info logs about missing items
                    this.logs_filters.status = 'Info';
                    this.logs_filters.message = 'not found in ERPNext';
                    $(this.wrapper).find('#status-filter').val('Info');
                    $(this.wrapper).find('#message-filter').val('not found in ERPNext');
                } else if (filter.message.includes('not found for Xero Contact')) {
                    // Show info logs about missing contacts
                    this.logs_filters.status = 'Info';
                    this.logs_filters.message = 'not found for Xero Contact';
                    $(this.wrapper).find('#status-filter').val('Info');
                    $(this.wrapper).find('#message-filter').val('not found for Xero Contact');
                } else if (filter.message.includes('No valid line items')) {
                    // Show warnings about invalid line items
                    this.logs_filters.status = 'Warning';
                    this.logs_filters.message = 'No valid line items';
                    $(this.wrapper).find('#status-filter').val('Warning');
                    $(this.wrapper).find('#message-filter').val('No valid line items');
                }
                
                this.logs_start = 0;
                this.load_logs_data(0, this.logs_filters);
                
                // Show a message to the user
                frappe.show_alert({
                    message: `Viewing logs filtered by: "${filter.message}"`,
                    indicator: 'blue'
                });
            }
        }, 100);
    }

    open_quick_mapping_dialog() {
        /**
         * Opens the Quick Account Mapping Dialog with unmapped accounts from recent errors
         */
        if (typeof QuickAccountMappingDialog === 'undefined') {
            frappe.msgprint({
                title: __('Error'),
                message: __('Quick Mapping Dialog component not loaded. Please refresh the page.'),
                indicator: 'red'
            });
            return;
        }
        
        QuickAccountMappingDialog.open_from_errors(7);
    }

    retry_job(log_name) {
        frappe.call({
            method: 'xero.xero.page.xero_sync_dashboard.xero_sync_dashboard.retry_failed_job',
            args: { log_name: log_name },
            callback: (r) => {
                if (r.message && r.message.success) {
                    frappe.show_alert({
                        message: 'Job queued for retry',
                        indicator: 'green'
                    });
                    this.load_logs_data(this.logs_start, this.logs_filters);
                }
            }
        });
    }

    view_log_details(log_name) {
        frappe.call({
            method: 'xero.xero.page.xero_sync_dashboard.xero_sync_dashboard.get_log_details',
            args: { log_name: log_name },
            callback: (r) => {
                if (r.message) {
                    this.show_log_details_dialog(r.message);
                }
            }
        });
    }

    show_log_details_dialog(log) {
        const dialog = new frappe.ui.Dialog({
            title: 'Sync Log Details',
            size: 'large',
            fields: [
                {
                    fieldtype: 'HTML',
                    fieldname: 'log_details',
                    options: `
                        <div class="log-details">
                            <div class="row">
                                <div class="col-md-6">
                                    <h6>Basic Information</h6>
                                    <table class="table table-sm">
                                        <tr><td><strong>Status:</strong></td><td><span class="badge badge-${this.get_status_color(log.status)}">${log.status}</span></td></tr>
                                        <tr><td><strong>Document:</strong></td><td>${log.erpnext_doc_type} ${log.erpnext_doc_name}</td></tr>
                                        <tr><td><strong>Timestamp:</strong></td><td>${frappe.datetime.str_to_user(log.timestamp)}</td></tr>
                                        <tr><td><strong>Category:</strong></td><td>${log.category}</td></tr>
                                    </table>
                                </div>
                                <div class="col-md-6">
                                    <h6>Technical Details</h6>
                                    <table class="table table-sm">
                                        <tr><td><strong>Xero ID:</strong></td><td>${log.xero_id || 'N/A'}</td></tr>
                                        <tr><td><strong>Operation:</strong></td><td>${log.operation || 'N/A'}</td></tr>
                                        <tr><td><strong>Retry Count:</strong></td><td>${log.retry_count || 0}</td></tr>
                                        <tr><td><strong>Processing Time:</strong></td><td>${log.processing_time || 'N/A'}s</td></tr>
                                    </table>
                                </div>
                            </div>
                            <div class="row mt-3">
                                <div class="col-md-12">
                                    <h6>Message</h6>
                                    <div class="alert alert-${this.get_status_color(log.status)}">
                                        ${log.message}
                                    </div>
                                </div>
                            </div>
                            ${log.error_details ? `
                                <div class="row mt-3">
                                    <div class="col-md-12">
                                        <h6>Error Details</h6>
                                        <pre class="bg-light p-3">${log.error_details}</pre>
                                    </div>
                                </div>
                            ` : ''}
                        </div>
                    `
                }
            ]
        });
        dialog.show();
    }

    test_connection() {
        frappe.call({
            method: 'xero.xero.page.xero_sync_dashboard.xero_sync_dashboard.test_xero_connection',
            callback: (r) => {
                if (r.message && r.message.success) {
                    frappe.show_alert({
                        message: 'Connection test successful',
                        indicator: 'green'
                    });
                } else {
                    frappe.show_alert({
                        message: r.message?.error || 'Connection test failed',
                        indicator: 'red'
                    });
                }
            }
        });
    }

    refresh_token() {
        frappe.call({
            method: 'xero.xero.page.xero_sync_dashboard.xero_sync_dashboard.refresh_xero_token',
            callback: (r) => {
                if (r.message && r.message.success) {
                    frappe.show_alert({
                        message: 'Token refreshed successfully',
                        indicator: 'green'
                    });
                    this.load_configuration();
                } else {
                    frappe.show_alert({
                        message: r.message?.error || 'Token refresh failed',
                        indicator: 'red'
                    });
                }
            }
        });
    }

    save_sync_settings() {
        const settings = {
            auto_sync_enabled: $(this.wrapper).find('#auto-sync').is(':checked'),
            sync_frequency: parseInt($(this.wrapper).find('#sync-frequency').val()),
            batch_size: parseInt($(this.wrapper).find('#batch-size').val()),
            max_retries: parseInt($(this.wrapper).find('#retry-attempts').val())
        };

        frappe.call({
            method: 'xero.xero.page.xero_sync_dashboard.xero_sync_dashboard.save_sync_settings',
            args: { settings: settings },
            callback: (r) => {
                if (r.message && r.message.success) {
                    frappe.show_alert({
                        message: 'Settings saved successfully',
                        indicator: 'green'
                    });
                } else {
                    frappe.show_alert({
                        message: r.message?.error || 'Failed to save settings',
                        indicator: 'red'
                    });
                }
            }
        });
    }

    view_queue(queue_name) {
        frappe.set_route('List', 'RQ Job', { queue: queue_name });
    }



    // Last Sync Attempts Tab
    load_last_sync_attempts() {
        this.show_loading();
        frappe.call({
            method: 'xero.xero.page.xero_sync_dashboard.xero_sync_dashboard.get_last_sync_attempts',
            callback: (r) => {
                this.hide_loading();
                if (r.message && !r.message.error) {
                    this.render_last_sync_attempts(r.message);
                } else {
                    this.show_error('Failed to load last sync attempts', r.message?.error);
                }
            }
        });
    }

    render_last_sync_attempts(data) {
        const last_sync_html = `
            <!-- Summary Stats -->
            <div class="overview-stats-grid" style="grid-template-columns: repeat(6,1fr);margin-bottom:24px;">
                <div class="overview-stat-card">
                    <div class="stat-value">${data.total_attempts || 0}</div>
                    <div class="stat-label">Total</div>
                </div>
                <div class="overview-stat-card">
                    <div class="stat-value" style="color:var(--ch-success);">${data.successful_attempts || 0}</div>
                    <div class="stat-label">Successful</div>
                </div>
                <div class="overview-stat-card">
                    <div class="stat-value" style="color:var(--ch-danger);">${data.failed_attempts || 0}</div>
                    <div class="stat-label">Failed</div>
                </div>
                <div class="overview-stat-card">
                    <div class="stat-value" style="color:var(--ch-warning);">${data.partial_success_attempts || 0}</div>
                    <div class="stat-label">Partial</div>
                </div>
                <div class="overview-stat-card">
                    <div class="stat-value" style="color:var(--ch-warning);">${data.warning_only_attempts || 0}</div>
                    <div class="stat-label">Warnings Only</div>
                </div>
                <div class="overview-stat-card">
                    <div class="stat-value" style="color:var(--ch-info);">${data.success_with_warnings_attempts || 0}</div>
                    <div class="stat-label">With Warnings</div>
                </div>
            </div>

            <!-- Sync Attempts List -->
            <div>
                ${data.sync_attempts && data.sync_attempts.length > 0 ?
                    data.sync_attempts.map(attempt => `
                        <div class="sync-attempt-block">
                            <div class="sync-attempt-header status-${this.get_sync_attempt_status_class(attempt.overall_status)}">
                                <div style="display:flex;align-items:center;gap:10px;">
                                    <i class="fa fa-${this.get_sync_direction_icon(attempt.sync_direction)}"></i>
                                    <div>
                                        <div>${attempt.sync_label ? attempt.sync_label : attempt.sync_direction}</div>
                                        ${attempt.sync_label ? `<div style="font-size:11px;opacity:0.85;font-weight:400;">${attempt.sync_direction}</div>` : ''}
                                    </div>
                                </div>
                                <div style="display:flex;align-items:center;gap:12px;">
                                    <span style="font-size:12px;font-weight:400;">${frappe.datetime.str_to_user(attempt.sync_time)}</span>
                                    <span class="badge badge-light">${attempt.overall_status}</span>
                                </div>
                            </div>
                            <div class="sync-attempt-body">
                                            <div class="row mb-3">
                                                <div class="col-md-12">
                                                    <strong>Entities Synced:</strong>
                                                    <div class="mt-2">
                                                        ${attempt.entities_synced.map(entity => `
                                                            <span class="badge badge-info mr-1 mb-1">${entity}</span>
                                                        `).join('')}
                                                    </div>
                                                </div>
                                            </div>
                                            
                                            <!-- Sync Issues Summary -->
                                            ${attempt.failure_summary && attempt.failure_summary.length > 0 ? `
                                                <div class="row mb-3">
                                                    <div class="col-md-12">
                                                        <div class="alert alert-warning mb-0">
                                                            <h6 class="mb-2"><i class="fa fa-exclamation-triangle"></i> Sync Issues Detected</h6>
                                                            <div class="table-responsive">
                                                                <table class="table table-sm table-bordered mb-0">
                                                                    <thead class="thead-light">
                                                                        <tr>
                                                                            <th>Issue Type</th>
                                                                            <th>Count</th>
                                                                            <th>Affected Documents</th>
                                                                            <th>Example Message</th>
                                                                        </tr>
                                                                    </thead>
                                                                    <tbody>
                                                                        ${attempt.failure_summary.map(failure => `
                                                                            <tr>
                                                                                <td><strong>${failure.failure_category}</strong></td>
                                                                                <td><span class="badge badge-warning">${failure.count}</span></td>
                                                                                <td class="text-truncate" style="max-width: 200px;" title="${failure.affected_docs || ''}">
                                                                                    <small>${failure.affected_docs || '-'}</small>
                                                                                </td>
                                                                                <td class="text-truncate" style="max-width: 300px;" title="${failure.example_message || ''}">
                                                                                    <small>${failure.example_message || '-'}</small>
                                                                                </td>
                                                                            </tr>
                                                                        `).join('')}
                                                                    </tbody>
                                                                </table>
                                                            </div>
                                                        </div>
                                                    </div>
                                                </div>
                                            ` : ''}
                                            
                                            <!-- Actionable Recommendations -->
                                            ${attempt.actionable_recommendations && attempt.actionable_recommendations.length > 0 ? `
                                                <div class="row mb-3">
                                                    <div class="col-md-12">
                                                        <h6 class="mb-2"><i class="fa fa-lightbulb"></i> Recommended Actions</h6>
                                                        ${attempt.actionable_recommendations.map(rec => `
                                                            <div class="alert alert-${rec.severity === 'high' ? 'danger' : rec.severity === 'medium' ? 'warning' : 'info'} mb-2">
                                                                <div class="d-flex align-items-start">
                                                                    <div class="mr-3">
                                                                        <i class="fa ${rec.icon} fa-2x"></i>
                                                                    </div>
                                                                    <div class="flex-grow-1">
                                                                        <h6 class="mb-1">${rec.title}</h6>
                                                                        <p class="mb-1">${rec.message}</p>
                                                                        <p class="mb-2"><strong>Action:</strong> ${rec.action}</p>
                                                                        <div class="btn-group" role="group">
                                                                            ${rec.type === 'account_mapping' ? `
                                                                                <button class="btn btn-sm btn-primary"
                                                                                        onclick="dashboard.open_quick_mapping_dialog()">
                                                                                    <i class="fa fa-magic"></i> Map Now
                                                                                </button>
                                                                            ` : ''}
                                                                            ${rec.action_button ? `
                                                                                <button class="btn btn-sm btn-outline-${rec.severity === 'high' ? 'danger' : 'warning'}"
                                                                                        onclick="${rec.action_button.route ? `frappe.set_route('${rec.action_button.route}')` : `dashboard.trigger_sync('${rec.action_button.entity}')`}">
                                                                                    ${rec.action_button.label}
                                                                                </button>
                                                                            ` : ''}
                                                                            ${rec.secondary_button ? `
                                                                                <button class="btn btn-sm btn-outline-info"
                                                                                        onclick="dashboard.view_filtered_logs(${JSON.stringify(rec.secondary_button.filter).replace(/"/g, '&quot;')})">
                                                                                    <i class="fa fa-list"></i> ${rec.secondary_button.label}
                                                                                </button>
                                                                            ` : ''}
                                                                        </div>
                                                                    </div>
                                                                </div>
                                                            </div>
                                                        `).join('')}
                                                    </div>
                                                </div>
                                            ` : ''}
                                            
                                            <!-- Detailed Item Status -->
                                            <div class="table-responsive">
                                                <table class="table table-sm table-bordered">
                                                    <thead class="thead-light">
                                                        <tr>
                                                            <th>Entity Type</th>
                                                            <th>Document Name</th>
                                                            <th>Status</th>
                                                            <th>Error Message</th>
                                                            <th>Timestamp</th>
                                                            <th>Actions</th>
                                                        </tr>
                                                    </thead>
                                                    <tbody>
                                                        ${attempt.items && attempt.items.length > 0 ?
                                                            attempt.items.map(item => `
                                                                <tr class="${item.status === 'Error' ? 'table-danger' : item.status === 'Success' ? 'table-success' : ''}">
                                                                    <td>${item.erpnext_doc_type || '-'}</td>
                                                                    <td>
                                                                        ${item.erpnext_doc_name ?
                                                                            `<a href="/app/${(item.erpnext_doc_type || '').toLowerCase().replace(/ /g, '-')}/${item.erpnext_doc_name}" target="_blank">
                                                                                ${item.erpnext_doc_name}
                                                                            </a>` :
                                                                            '-'
                                                                        }
                                                                    </td>
                                                                    <td>
                                                                        <span class="badge badge-${this.get_status_color(item.status)}">
                                                                            ${item.status}
                                                                        </span>
                                                                    </td>
                                                                    <td class="text-truncate" style="max-width: 300px;" title="${item.message || ''}">
                                                                        ${item.status === 'Error' ? (item.message || 'No error message') : '-'}
                                                                    </td>
                                                                    <td>
                                                                        <small>${frappe.datetime.comment_when(item.timestamp)}</small>
                                                                    </td>
                                                                    <td>
                                                                        ${item.status === 'Error' && item.log_name ?
                                                                            `<button class="btn btn-xs btn-outline-warning" onclick="dashboard.retry_job('${item.log_name}')">
                                                                                <i class="fa fa-redo"></i> Retry
                                                                            </button>` :
                                                                            ''
                                                                        }
                                                                        ${item.log_name ?
                                                                            `<button class="btn btn-xs btn-outline-info ml-1" onclick="dashboard.view_log_details('${item.log_name}')">
                                                                                <i class="fa fa-eye"></i>
                                                                            </button>` :
                                                                            ''
                                                                        }
                                                                    </td>
                                                                </tr>
                                                            `).join('') :
                                                            '<tr><td colspan="6" class="text-center text-muted">No items in this sync attempt</td></tr>'
                                                        }
                                                    </tbody>
                                                </table>
                                            </div>
                                            
                                            <!-- Summary Stats for this attempt -->
                                            <div class="row mt-3">
                                                <div class="col-md-12">
                                                    <div class="d-flex justify-content-between align-items-center">
                                                        <div>
                                                        <strong>Summary:</strong>
                                                        <span class="badge badge-success ml-2">${attempt.success_count || 0} Success</span>
                                                        <span class="badge badge-danger ml-2">${attempt.error_count || 0} Failed</span>
                                                        <span class="badge badge-warning ml-2">${attempt.warning_count || 0} Warnings</span>
                                                        ${attempt.skipped_count > 0 ? `<span class="badge badge-secondary ml-2">${attempt.skipped_count} Skipped</span>` : ''}
                                                        </div>
                                                        <div>
                                                            <small class="text-muted">
                                                                Duration: ${attempt.duration ? `${attempt.duration}s` : 'N/A'}
                                                            </small>
                                                         </div>
                                                     </div>
                                                 </div>
                                             </div>
                            </div>
                        </div>
                    `).join('') :
                    '<div class="card" style="padding:20px;text-align:center;color:var(--ch-text-muted);">No sync attempts found in the last 7 days.</div>'
                }
            </div>
        `;

        $(this.wrapper).find('#last-sync').html(last_sync_html);
    }

    get_sync_attempt_status_class(status) {
        const classes = {
            'Success': 'success',
            'Failed': 'failed',
            'Partial Success': 'partial',
            'Warnings Only': 'warnings',
            'Success with Warnings': 'info'
        };
        return classes[status] || 'info';
    }

    get_sync_attempt_color(status) {
        const colors = {
            'Success': 'success',
            'Failed': 'danger',
            'Partial Success': 'warning',
            'Warnings Only': 'warning',
            'Success with Warnings': 'info'
        };
        return colors[status] || 'secondary';
    }

    get_sync_direction_icon(direction) {
        if (direction && direction.includes('→')) {
            if (direction.includes('ERPNext → Xero')) return 'arrow-right';
            if (direction.includes('Xero → ERPNext')) return 'arrow-left';
            if (direction.includes('Both')) return 'exchange-alt';
        }
        return 'sync';
    }

    // Performance Metrics Tab
    load_performance_metrics() {
        this.show_loading();
        frappe.call({
            method: 'xero.xero.page.xero_sync_dashboard.xero_sync_dashboard.get_sync_performance_metrics',
            callback: (r) => {
                this.hide_loading();
                if (r.message && !r.message.error) {
                    this.render_performance_metrics(r.message);
                } else {
                    this.show_error('Failed to load performance metrics', r.message?.error);
                }
            }
        });
    }

    render_performance_metrics(data) {
        const performance_html = `
            <div class="row">
                <!-- Summary Metrics -->
                <div class="col-md-12 mb-4">
                    <div class="row">
                        <div class="col-md-4">
                            <div class="card">
                                <div class="card-body text-center">
                                    <h3 class="text-primary">${data.throughput || 0}</h3>
                                    <p class="text-muted">Records/Minute</p>
                                    <small>Sync throughput (last hour)</small>
                                </div>
                            </div>
                        </div>
                        <div class="col-md-4">
                            <div class="card">
                                <div class="card-body text-center">
                                    <h3 class="text-warning">${data.total_pending || 0}</h3>
                                    <p class="text-muted">Pending Documents</p>
                                    <small>Total in queue</small>
                                </div>
                            </div>
                        </div>
                        <div class="col-md-4">
                            <div class="card">
                                <div class="card-body text-center">
                                    <h3 class="text-${data.oldest_pending && data.oldest_pending.days_pending > 7 ? 'danger' : 'info'}">
                                        ${data.oldest_pending ? data.oldest_pending.days_pending : 0}
                                    </h3>
                                    <p class="text-muted">Oldest Pending (days)</p>
                                    <small>${data.oldest_pending ? data.oldest_pending.name : 'None'}</small>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Sync Latency by Entity -->
                ${data.latency_by_entity && data.latency_by_entity.length > 0 ? `
                    <div class="col-md-12 mb-4">
                        <div class="card">
                            <div class="card-header">
                                <h5 class="mb-0"><i class="fa fa-clock"></i> Average Sync Latency by Entity (Last 24h)</h5>
                            </div>
                            <div class="card-body">
                                <div class="table-responsive">
                                    <table class="table table-sm">
                                        <thead>
                                            <tr>
                                                <th>Entity Type</th>
                                                <th>Avg Latency</th>
                                                <th>Min</th>
                                                <th>Max</th>
                                                <th>Total Syncs</th>
                                            </tr>
                                        </thead>
                                        <tbody>
                                            ${data.latency_by_entity.map(entity => `
                                                <tr>
                                                    <td>${entity.erpnext_doc_type}</td>
                                                    <td>
                                                        <span class="badge badge-${entity.avg_latency > 5 ? 'danger' : entity.avg_latency > 2 ? 'warning' : 'success'}">
                                                            ${(entity.avg_latency || 0).toFixed(2)}s
                                                        </span>
                                                    </td>
                                                    <td>${(entity.min_latency || 0).toFixed(2)}s</td>
                                                    <td>${(entity.max_latency || 0).toFixed(2)}s</td>
                                                    <td>${entity.total_syncs || 0}</td>
                                                </tr>
                                            `).join('')}
                                        </tbody>
                                    </table>
                                </div>
                            </div>
                        </div>
                    </div>
                ` : ''}

                <!-- Slowest Sync Operations -->
                ${data.slowest_syncs && data.slowest_syncs.length > 0 ? `
                    <div class="col-md-6 mb-4">
                        <div class="card">
                            <div class="card-header">
                                <h5 class="mb-0"><i class="fa fa-hourglass-end"></i> Slowest Operations (Last 24h)</h5>
                            </div>
                            <div class="card-body">
                                <div class="table-responsive">
                                    <table class="table table-sm">
                                        <thead>
                                            <tr>
                                                <th>Document</th>
                                                <th>Time</th>
                                                <th>When</th>
                                            </tr>
                                        </thead>
                                        <tbody>
                                            ${data.slowest_syncs.map(sync => `
                                                <tr>
                                                    <td>
                                                        <small>${sync.erpnext_doc_type}<br>${sync.erpnext_doc_name}</small>
                                                    </td>
                                                    <td>
                                                        <span class="badge badge-danger">${(sync.processing_time || 0).toFixed(2)}s</span>
                                                    </td>
                                                    <td>
                                                        <small>${frappe.datetime.comment_when(sync.timestamp)}</small>
                                                    </td>
                                                </tr>
                                            `).join('')}
                                        </tbody>
                                    </table>
                                </div>
                            </div>
                        </div>
                    </div>
                ` : ''}

                <!-- Queue Depth -->
                ${data.queue_depth && data.queue_depth.length > 0 ? `
                    <div class="col-md-6 mb-4">
                        <div class="card">
                            <div class="card-header">
                                <h5 class="mb-0"><i class="fa fa-tasks"></i> Queue Depth by Entity</h5>
                            </div>
                            <div class="card-body">
                                <div class="table-responsive">
                                    <table class="table table-sm">
                                        <thead>
                                            <tr>
                                                <th>DocType</th>
                                                <th>Pending Count</th>
                                            </tr>
                                        </thead>
                                        <tbody>
                                            ${data.queue_depth.map(q => `
                                                <tr>
                                                    <td>${q.doctype}</td>
                                                    <td>
                                                        <span class="badge badge-${q.pending_count > 100 ? 'danger' : q.pending_count > 50 ? 'warning' : 'info'}">
                                                            ${q.pending_count}
                                                        </span>
                                                    </td>
                                                </tr>
                                            `).join('')}
                                        </tbody>
                                    </table>
                                </div>
                            </div>
                        </div>
                    </div>
                ` : ''}
            </div>
        `;

        $(this.wrapper).find('#performance').html(performance_html);
    }



    // Auto-refresh functionality
    start_auto_refresh() {
        if (this.auto_refresh) {
            this.refresh_interval = setInterval(() => {
                this.refresh_current_tab();
            }, 30000); // Refresh every 30 seconds
        }
    }

    stop_auto_refresh() {
        if (this.refresh_interval) {
            clearInterval(this.refresh_interval);
            this.refresh_interval = null;
        }
    }

    toggle_auto_refresh() {
        this.auto_refresh = !this.auto_refresh;
        if (this.auto_refresh) {
            this.start_auto_refresh();
            frappe.show_alert({
                message: 'Auto-refresh enabled',
                indicator: 'green'
            });
        } else {
            this.stop_auto_refresh();
            frappe.show_alert({
                message: 'Auto-refresh disabled',
                indicator: 'orange'
            });
        }
    }

    refresh_current_tab() {
        switch(this.current_tab) {
            case 'overview':
                this.load_overview();
                break;
            case 'sync-ops':
                this.load_sync_operations();
                break;
            case 'last-sync':
                this.load_last_sync_attempts();
                break;
            case 'logs':
                this.load_logs_data(this.logs_start, this.logs_filters);
                break;
            case 'analytics':
                this.load_analytics();
                break;
            case 'entities':
                this.load_entity_status();
                break;
        }
    }

    export_logs() {
        frappe.call({
            method: 'xero.xero.page.xero_sync_dashboard.xero_sync_dashboard.export_logs',
            args: { filters: this.logs_filters },
            callback: (r) => {
                if (r.message && r.message.file_url) {
                    window.open(r.message.file_url, '_blank');
                    frappe.show_alert({
                        message: 'Logs exported successfully',
                        indicator: 'green'
                    });
                }
            }
        });
    }

    show_error(title, message) {
        $(this.wrapper).find('.tab-content.active').html(`
            <div class="alert alert-danger">
                <h5>${title}</h5>
                <p>${message || 'An unexpected error occurred.'}</p>
                <button class="btn btn-outline-danger" onclick="dashboard.refresh_current_tab()">
                    <i class="fa fa-refresh"></i> Retry
                </button>
            </div>
        `);
    }

    // Cleanup on page unload
    destroy() {
        this.stop_auto_refresh();
    }
}

// Cleanup when page is destroyed
$(window).on('beforeunload', function() {
    if (window.dashboard) {
        window.dashboard.destroy();
    }
});
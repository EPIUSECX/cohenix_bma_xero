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
        this.load_lucide().then(() => {
            this.setup_page_actions();
            this.render_layout();
            this.setup_tabs();
            this.load_overview();
            this.start_auto_refresh();
        });
    }

    load_lucide() {
        return new Promise((resolve) => {
            if (window.lucide) {
                resolve();
                return;
            }
            const script = document.createElement('script');
            script.src = 'https://unpkg.com/lucide@0.344.0/dist/umd/lucide.min.js';
            script.onload = () => resolve();
            script.onerror = () => {
                console.warn('Lucide CDN failed to load, falling back to Font Awesome');
                resolve();
            };
            document.head.appendChild(script);
        });
    }

    create_lucide_icons() {
        if (window.lucide) {
            try { lucide.createIcons(); } catch(e) { /* ignore */ }
        }
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
        // Add Cohenix HR theme CSS — tokens extracted from ESS_Cohenix_HR reference app
        $(`<style>
            /* ============================================================
               XERO SYNC DASHBOARD — Cohenix HR Design System
               Tokens sourced from index-DNPSLMMZ.css :root variables
               Primary: hsl(221,78%,58%) | Font: Source Sans Pro
               ============================================================ */

            :root {
                /* Primary — dusty blue */
                --ch-primary:          #5B8AC4;
                --ch-primary-dark:     #4A78B0;   /* hover */
                --ch-primary-light:    #F0F4FA;   /* tint */

                /* Semantic colors — muted/dusty tones */
                --ch-success:          #5BA88A;   /* dusty green */
                --ch-success-bg:       #F0F8F4;   /* success tint */
                --ch-success-border:   #C2E0D2;   /* success border */
                --ch-warning:          #C4923A;   /* dusty amber */
                --ch-warning-bg:       #FBF7F0;   /* warning tint */
                --ch-warning-border:   #EDDCB8;   /* warning border */
                --ch-danger:           #B87D5A;   /* dusty terracotta */
                --ch-danger-alt:       #C45B5B;   /* muted red for error states */
                --ch-danger-bg:        #FBF3EF;   /* destructive tint */
                --ch-danger-border:    #E8CCBB;   /* destructive border */
                --ch-info:             #5B8AC4;   /* same as primary */
                --ch-info-bg:          #F0F4FA;

                /* Surfaces — hsl(210,20%,98%) background, white cards */
                --ch-bg:               #F7F9FB;   /* hsl(210,20%,98%) */
                --ch-surface:          #FFFFFF;   /* hsl(0,0%,100%) */
                --ch-border:           #ECEEF0;   /* hsl(215,5%,93%) */
                --ch-border-strong:    #D1D5DB;

                /* Typography — hsl(210,15%,12%) foreground */
                --ch-text:             #1A1F26;   /* hsl(210,15%,12%) */
                --ch-text-muted:       #7F8A96;   /* hsl(210,10%,55%) */
                --ch-text-subtle:      #9CA3AF;

                /* Shadows */
                --ch-shadow-sm:        0 1px 2px 0 rgba(0,0,0,0.05);
                --ch-shadow-md:        0 4px 6px -1px rgba(0,0,0,0.1), 0 2px 4px -2px rgba(0,0,0,0.1);
                --ch-shadow-hover:     0 4px 14px 0 hsl(221 78% 58% / 0.35);

                /* Radii — --radius: 0.625rem = 10px */
                --ch-radius-sm:        6px;
                --ch-radius-md:        10px;   /* = var(--radius) */
                --ch-radius-lg:        12px;
                --ch-radius-pill:      9999px;

                /* Font */
                --ch-font:             'Source Sans Pro', 'Segoe UI', system-ui, sans-serif;
            }

            /* Dark mode — from .dark in reference CSS */
            html[data-theme-mode="dark"] {
                --ch-bg:               #0D1117;   /* hsl(222,47%,7%) */
                --ch-surface:          #161B22;   /* hsl(222,32%,12%) */
                --ch-border:           #21262D;   /* hsl(217,30%,22%) */
                --ch-text:             #F0F6FC;   /* hsl(210,5%,96%) */
                --ch-text-muted:       #8B949E;   /* hsl(215,12%,70%) */
                --ch-primary-light:    #1C2A4A;
                --ch-success-bg:       #0D2818;
                --ch-warning-bg:       #2D1F00;
                --ch-danger-bg:        #2D1500;
                --ch-info-bg:          #1C2A4A;
            }

            /* ─── Page Container ─── */
            .xero-dashboard-container {
                padding: 24px;
                background: var(--ch-bg);
                min-height: calc(100vh - 150px);
                color: var(--ch-text);
                font-family: var(--ch-font);
                font-size: 14px;
                line-height: 1.5;
                -webkit-font-smoothing: antialiased;
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
                background: transparent;
                border: none;
                border-radius: var(--ch-radius-pill);
                padding: 7px 18px;
                font-size: 13px;
                font-weight: 500;
                line-height: 1.4;
                transition: background 0.15s, color 0.15s;
                white-space: nowrap;
                display: inline-flex;
                align-items: center;
                gap: 6px;
            }

            .xero-dashboard-container .nav-tabs .nav-link svg {
                width: 15px;
                height: 15px;
            }

            .xero-dashboard-container .nav-tabs .nav-link:hover:not(.active) {
                background: var(--ch-primary-light);
                color: var(--ch-primary);
                text-decoration: none;
            }

            .xero-dashboard-container .nav-tabs .nav-link.active {
                background: var(--ch-primary) !important;
                color: #fff !important;
                box-shadow: var(--ch-shadow-md);
            }

            .xero-dashboard-container .nav-tabs .nav-link.active svg {
                color: #fff;
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

            /* ─── Status Badges — outlined pill style (matches reference "Submitted"/"Paid") ─── */
            .badge, span.badge {
                display: inline-flex;
                align-items: center;
                padding: 2px 9px;
                border-radius: var(--ch-radius-pill);
                font-size: 11px;
                font-weight: 600;
                letter-spacing: 0.02em;
                line-height: 1.6;
                border: 1px solid currentColor;
            }

            /* Success — outlined green like "Submitted"/"Paid" in reference */
            .badge-success, .badge.success, span.indicator-pill.green {
                background: var(--ch-success-bg) !important;
                color: var(--ch-success) !important;
                border-color: var(--ch-success-border) !important;
            }

            /* Danger — outlined red */
            .badge-danger, .badge.error, span.indicator-pill.red {
                background: var(--ch-danger-bg) !important;
                color: var(--ch-danger-alt) !important;
                border-color: var(--ch-danger-border) !important;
            }

            /* Warning — outlined amber */
            .badge-warning, .badge.warning, span.indicator-pill.orange {
                background: var(--ch-warning-bg) !important;
                color: var(--ch-warning) !important;
                border-color: var(--ch-warning-border) !important;
            }

            /* Info — outlined blue */
            .badge-info, .badge.info, span.indicator-pill.blue {
                background: var(--ch-info-bg) !important;
                color: var(--ch-info) !important;
                border-color: rgba(74,127,229,0.3) !important;
            }

            /* Primary — solid blue pill (like "NET PAY" in reference) */
            .badge-primary {
                background: var(--ch-primary) !important;
                color: #fff !important;
                border-color: var(--ch-primary) !important;
            }

            .badge-secondary {
                background: transparent !important;
                color: var(--ch-text-muted) !important;
                border-color: var(--ch-border) !important;
            }

            .badge-light {
                background: var(--ch-bg) !important;
                color: var(--ch-text) !important;
                border-color: var(--ch-border) !important;
            }

            /* ─── Tables — clean row dividers, no zebra (matches reference payslips list) ─── */
            .table {
                color: var(--ch-text);
                border-collapse: collapse;
                width: 100%;
                font-size: 14px;
            }

            .table thead th {
                background: transparent;
                color: var(--ch-text-muted);
                font-size: 11px;
                font-weight: 600;
                letter-spacing: 0.08em;
                text-transform: uppercase;
                border-bottom: 1px solid var(--ch-border);
                border-top: none;
                padding: 10px 16px;
                white-space: nowrap;
            }

            .table tbody td {
                border-top: 1px solid var(--ch-border);
                padding: 12px 16px;
                color: var(--ch-text);
                vertical-align: middle;
                background: transparent;
            }

            /* No zebra — clean white rows, subtle hover */
            .table tbody tr:hover td {
                background: hsl(221 78% 58% / 0.04);
            }

            /* Row status tinting — very subtle */
            .table-danger td { background: hsl(27 50% 58% / 0.06) !important; }
            .table-success td { background: hsl(142 76% 36% / 0.06) !important; }

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

            /* ─── Manual Sync Operations — Modern Minimalist ─── */
            .xero-sync-header-modern {
                background: var(--ch-surface);
                border: 1px solid var(--ch-border);
                border-radius: var(--ch-radius-lg);
                padding: 20px 24px;
                margin-bottom: 20px;
                display: flex;
                align-items: center;
                justify-content: space-between;
            }

            .xero-sync-header-modern .xero-sync-title {
                font-size: 17px;
                font-weight: 700;
                margin: 0;
                color: var(--ch-text);
                display: block;
            }

            .xero-sync-header-modern .xero-sync-subtitle {
                font-size: 13px;
                color: var(--ch-text-muted);
                margin: 4px 0 0 0;
            }

            .xero-sync-ready-badge {
                display: inline-flex;
                align-items: center;
                gap: 6px;
                background: var(--ch-success-bg);
                color: var(--ch-success);
                border: 1px solid var(--ch-success-border);
                border-radius: var(--ch-radius-pill);
                padding: 5px 14px;
                font-size: 12px;
                font-weight: 600;
            }

            .xero-sync-ready-badge svg,
            .xero-sync-ready-badge i {
                width: 14px;
                height: 14px;
            }

            /* Direction sections */
            .sync-direction-card {
                background: var(--ch-surface);
                border: 1px solid var(--ch-border);
                border-radius: var(--ch-radius-lg);
                padding: 24px;
                margin-bottom: 20px;
            }

            .sync-direction-card.disabled-section {
                opacity: 0.6;
                pointer-events: none;
                position: relative;
            }

            .sync-direction-card.disabled-section::after {
                content: '';
                position: absolute;
                top: 0; left: 0; right: 0; bottom: 0;
                background: rgba(128,128,128,0.08);
                border-radius: var(--ch-radius-lg);
                z-index: 1;
            }

            .sync-direction-header {
                display: flex;
                align-items: center;
                gap: 14px;
                margin-bottom: 20px;
            }

            .sync-direction-icon {
                width: 38px;
                height: 38px;
                border-radius: 50%;
                display: flex;
                align-items: center;
                justify-content: center;
                flex-shrink: 0;
            }

            .sync-direction-icon svg {
                width: 18px;
                height: 18px;
                color: #fff;
            }

            .sync-direction-icon.to-xero   { background: #7BA3CC; }
            .sync-direction-icon.from-xero { background: #7BB89E; }

            .sync-direction-info h3 {
                margin: 0;
                font-size: 15px;
                font-weight: 700;
                color: var(--ch-text);
            }

            .sync-direction-info p {
                margin: 3px 0 0 0;
                font-size: 13px;
                color: var(--ch-text-muted);
            }

            /* Chip-style sync buttons */
            .sync-chips-grid {
                display: flex;
                flex-wrap: wrap;
                gap: 10px;
            }

            .sync-chip-btn {
                display: inline-flex;
                align-items: center;
                gap: 8px;
                padding: 8px 16px;
                background: var(--ch-surface);
                border: 1px solid var(--ch-border);
                border-radius: var(--ch-radius-md);
                cursor: pointer;
                transition: border-color 0.15s, box-shadow 0.15s, background 0.15s;
                text-decoration: none !important;
                color: var(--ch-text) !important;
                font-size: 13px;
                font-weight: 500;
                line-height: 1.4;
                white-space: nowrap;
            }

            .sync-chip-btn:hover {
                border-color: var(--ch-primary);
                box-shadow: 0 2px 8px rgba(74,127,229,0.12);
                background: var(--ch-primary-light);
                text-decoration: none !important;
                color: var(--ch-text) !important;
            }

            .sync-chip-btn:active {
                transform: scale(0.97);
            }

            .sync-chip-btn.disabled {
                opacity: 0.5;
                cursor: not-allowed;
                pointer-events: none;
            }

            .sync-chip-btn svg,
            .sync-chip-btn .chip-icon {
                width: 16px;
                height: 16px;
                flex-shrink: 0;
            }

            /* Chip icon colors — dusty/muted palette */
            .chip-icon-blue    { color: #5B7EC2; }
            .chip-icon-indigo  { color: #5A8AB5; }
            .chip-icon-green   { color: #5BA88A; }
            .chip-icon-orange  { color: #C4923A; }
            .chip-icon-purple  { color: #8B6FC0; }
            .chip-icon-red     { color: #C07A50; }
            .chip-icon-teal    { color: #4A9BA8; }
            .chip-icon-violet  { color: #9B6EAD; }
            .chip-icon-gray    { color: #7A8490; }
            .chip-icon-crimson { color: #B85A5A; }

            /* ─── Bulk Operations — Modern ─── */
            .bulk-ops-card {
                background: var(--ch-surface);
                border: 1px solid var(--ch-border);
                border-radius: var(--ch-radius-lg);
                padding: 20px 24px;
                margin-bottom: 20px;
            }

            .bulk-ops-header {
                display: flex;
                align-items: center;
                gap: 10px;
                margin-bottom: 16px;
                font-size: 15px;
                font-weight: 700;
                color: var(--ch-text);
            }

            .bulk-ops-header svg {
                width: 18px;
                height: 18px;
                color: var(--ch-text-muted);
            }

            .bulk-ops-row {
                display: flex;
                gap: 12px;
                flex-wrap: wrap;
            }

            .bulk-btn {
                display: inline-flex;
                align-items: center;
                gap: 8px;
                padding: 9px 18px;
                border-radius: var(--ch-radius-md);
                font-size: 13px;
                font-weight: 500;
                cursor: pointer;
                transition: all 0.15s;
                border: 1px solid transparent;
                line-height: 1.4;
            }

            .bulk-btn svg {
                width: 15px;
                height: 15px;
            }

            .bulk-btn-danger {
                background: transparent;
                border-color: var(--ch-danger-alt);
                color: var(--ch-danger-alt);
            }

            .bulk-btn-danger:hover {
                background: rgba(220,38,38,0.06);
            }

            .bulk-btn-primary {
                background: var(--ch-success);
                border-color: var(--ch-success);
                color: #fff;
            }

            .bulk-btn-primary:hover {
                background: #4D9578;
                box-shadow: 0 2px 8px rgba(91,168,138,0.3);
            }

            .bulk-btn-ghost {
                background: transparent;
                border-color: var(--ch-border);
                color: var(--ch-text-muted);
            }

            .bulk-btn-ghost:hover {
                border-color: var(--ch-text-muted);
                color: var(--ch-text);
            }

            /* ─── Queue Status — Stat Cards ─── */
            .queue-stats-grid {
                display: grid;
                grid-template-columns: repeat(4, 1fr);
                gap: 16px;
            }

            .queue-stat-card {
                background: var(--ch-surface);
                border: 1px solid var(--ch-border);
                border-radius: var(--ch-radius-lg);
                padding: 20px;
                text-align: center;
            }

            .queue-stat-card .queue-stat-icon {
                margin-bottom: 8px;
            }

            .queue-stat-card .queue-stat-icon svg {
                width: 20px;
                height: 20px;
                color: var(--ch-text-muted);
            }

            .queue-stat-card .queue-stat-icon.icon-queued svg    { color: var(--ch-text-muted); }
            .queue-stat-card .queue-stat-icon.icon-processing svg { color: var(--ch-primary); }
            .queue-stat-card .queue-stat-icon.icon-completed svg  { color: var(--ch-success); }
            .queue-stat-card .queue-stat-icon.icon-failed svg     { color: var(--ch-danger-alt); }

            .queue-stat-card .queue-stat-value {
                font-size: 28px;
                font-weight: 700;
                color: var(--ch-text);
                line-height: 1.2;
            }

            .queue-stat-card .queue-stat-label {
                font-size: 12px;
                color: var(--ch-text-muted);
                margin-top: 4px;
            }

            .queue-section-header {
                display: flex;
                align-items: center;
                gap: 10px;
                margin-bottom: 16px;
                font-size: 15px;
                font-weight: 700;
                color: var(--ch-text);
            }

            .queue-section-header svg {
                width: 18px;
                height: 18px;
                color: var(--ch-text-muted);
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

            /* ─── Last Sync Attempts — Modern ─── */
            .sync-attempt-block {
                background: var(--ch-surface);
                border: 1px solid var(--ch-border);
                border-radius: var(--ch-radius-lg);
                margin-bottom: 16px;
                overflow: hidden;
                border-left: 3px solid var(--ch-border);
            }

            .sync-attempt-block.attempt-success  { border-left-color: var(--ch-success); }
            .sync-attempt-block.attempt-failed   { border-left-color: var(--ch-danger-alt); }
            .sync-attempt-block.attempt-partial  { border-left-color: var(--ch-warning); }
            .sync-attempt-block.attempt-warnings { border-left-color: var(--ch-warning); }
            .sync-attempt-block.attempt-info     { border-left-color: var(--ch-info); }

            .sync-attempt-header {
                display: flex;
                align-items: center;
                justify-content: space-between;
                padding: 14px 20px;
                cursor: pointer;
                font-weight: 600;
                font-size: 13px;
                color: var(--ch-text);
                background: var(--ch-surface);
                border-bottom: 1px solid var(--ch-border);
            }

            .sync-attempt-header svg {
                width: 16px;
                height: 16px;
            }

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

            /* ─── Overview Connection Banner — Modern ─── */
            .xero-connection-banner {
                background: var(--ch-surface);
                border: 1px solid var(--ch-border);
                border-radius: var(--ch-radius-lg);
                padding: 20px 24px;
                margin-bottom: 20px;
                display: flex;
                align-items: center;
                justify-content: space-between;
                flex-wrap: wrap;
                gap: 16px;
            }

            .xero-connection-left {
                display: flex;
                align-items: center;
                gap: 12px;
            }

            .xero-connection-icon {
                width: 40px;
                height: 40px;
                border-radius: 50%;
                background: #7BA3CC;
                display: flex;
                align-items: center;
                justify-content: center;
                flex-shrink: 0;
            }

            .xero-connection-icon svg {
                width: 20px;
                height: 20px;
                color: #fff;
            }

            .xero-connection-title {
                font-size: 17px;
                font-weight: 700;
                color: var(--ch-text);
                display: flex;
                align-items: center;
                gap: 10px;
            }

            .xero-connection-meta {
                display: flex;
                gap: 40px;
                flex-wrap: wrap;
            }

            .xero-connection-meta-item {
                text-align: left;
            }

            .xero-connection-meta-item label {
                font-size: 10px;
                text-transform: uppercase;
                letter-spacing: 0.08em;
                color: var(--ch-text-muted);
                display: block;
                margin-bottom: 2px;
                font-weight: 600;
            }

            .xero-connection-meta-item span {
                font-size: 13px;
                font-weight: 600;
                color: var(--ch-text);
            }

            /* Overview stat cards — modern layout */
            .overview-stat-card {
                display: flex;
                align-items: flex-start;
                justify-content: space-between;
                text-align: left;
                padding: 20px 24px;
            }

            .overview-stat-card .stat-text {
                flex: 1;
            }

            .overview-stat-card .stat-label-top {
                font-size: 12px;
                color: var(--ch-text-muted);
                margin-bottom: 4px;
            }

            .overview-stat-card .stat-value {
                font-size: 32px;
                font-weight: 700;
                color: var(--ch-text);
                line-height: 1.1;
            }

            .overview-stat-card .stat-icon-circle {
                width: 40px;
                height: 40px;
                border-radius: 50%;
                display: flex;
                align-items: center;
                justify-content: center;
                flex-shrink: 0;
            }

            .overview-stat-card .stat-icon-circle svg {
                width: 20px;
                height: 20px;
            }

            .stat-icon-circle.icon-success { background: var(--ch-success-bg); }
            .stat-icon-circle.icon-success svg { color: var(--ch-success); }
            .stat-icon-circle.icon-danger { background: var(--ch-danger-bg); }
            .stat-icon-circle.icon-danger svg { color: var(--ch-danger-alt); }
            .stat-icon-circle.icon-info { background: var(--ch-info-bg); }
            .stat-icon-circle.icon-info svg { color: var(--ch-info); }
            .stat-icon-circle.icon-primary { background: var(--ch-primary-light); }
            .stat-icon-circle.icon-primary svg { color: var(--ch-primary); }

            /* Recent Errors — modern list */
            .errors-card, .jobs-card {
                background: var(--ch-surface);
                border: 1px solid var(--ch-border);
                border-radius: var(--ch-radius-lg);
                margin-bottom: 20px;
                overflow: hidden;
            }

            .section-card-header {
                display: flex;
                align-items: center;
                gap: 10px;
                padding: 16px 24px;
                font-size: 15px;
                font-weight: 700;
                color: var(--ch-text);
                border-bottom: 1px solid var(--ch-border);
            }

            .section-card-header svg {
                width: 18px;
                height: 18px;
                color: var(--ch-text-muted);
            }

            .error-list-item {
                padding: 16px 24px;
                border-bottom: 1px solid var(--ch-border);
                position: relative;
            }

            .error-list-item:last-child {
                border-bottom: none;
            }

            .error-list-item .error-top-row {
                display: flex;
                align-items: baseline;
                gap: 10px;
                margin-bottom: 4px;
            }

            .error-list-item .error-doc-title {
                font-size: 14px;
                font-weight: 600;
                color: var(--ch-text);
            }

            .error-list-item .error-time {
                font-size: 12px;
                color: var(--ch-text-muted);
            }

            .error-list-item .error-message {
                font-size: 13px;
                color: var(--ch-text-muted);
                margin-bottom: 6px;
                line-height: 1.4;
            }

            .error-list-item .error-dot {
                position: absolute;
                top: 20px;
                right: 24px;
                width: 8px;
                height: 8px;
                border-radius: 50%;
                background: var(--ch-danger-alt);
            }

            .empty-state {
                padding: 40px 24px;
                text-align: center;
                color: var(--ch-text-muted);
            }

            .empty-state svg {
                width: 32px;
                height: 32px;
                color: var(--ch-border-strong);
                margin-bottom: 10px;
            }

            .empty-state p {
                margin: 0;
                font-size: 13px;
            }

            /* ─── Sync Logs — Modern ─── */
            .logs-header-card {
                background: var(--ch-surface);
                border: 1px solid var(--ch-border);
                border-radius: var(--ch-radius-lg);
                padding: 16px 24px;
                margin-bottom: 20px;
                display: flex;
                align-items: center;
                gap: 10px;
                font-size: 15px;
                font-weight: 700;
                color: var(--ch-text);
            }

            .logs-header-card svg {
                width: 18px;
                height: 18px;
                color: var(--ch-text-muted);
            }

            .logs-filters-card {
                background: var(--ch-surface);
                border: 1px solid var(--ch-border);
                border-radius: var(--ch-radius-lg);
                padding: 16px 24px;
                margin-bottom: 20px;
                display: flex;
                align-items: center;
                gap: 12px;
                flex-wrap: wrap;
            }

            .logs-filters-card select,
            .logs-filters-card input {
                border: 1px solid var(--ch-border);
                border-radius: var(--ch-radius-pill);
                padding: 8px 16px;
                font-size: 13px;
                color: var(--ch-text);
                background: var(--ch-surface);
                outline: none;
            }

            .logs-filters-card select {
                min-width: 130px;
                appearance: auto;
            }

            .logs-filters-card input {
                flex: 1;
                min-width: 200px;
            }

            .logs-filters-card select:focus,
            .logs-filters-card input:focus {
                border-color: var(--ch-primary);
                box-shadow: 0 0 0 3px var(--ch-primary-light);
            }

            .logs-filter-btn {
                display: inline-flex;
                align-items: center;
                gap: 6px;
                padding: 8px 20px;
                background: var(--ch-primary);
                color: #fff;
                border: none;
                border-radius: var(--ch-radius-pill);
                font-size: 13px;
                font-weight: 500;
                cursor: pointer;
                transition: background 0.15s;
                margin-left: auto;
            }

            .logs-filter-btn:hover {
                background: var(--ch-primary-dark);
            }

            .logs-filter-btn svg {
                width: 14px;
                height: 14px;
            }

            .logs-table-card {
                background: var(--ch-surface);
                border: 1px solid var(--ch-border);
                border-radius: var(--ch-radius-lg);
                overflow: hidden;
            }

            .logs-table-card .table {
                margin-bottom: 0;
            }

            .logs-action-link {
                display: inline-flex;
                align-items: center;
                gap: 4px;
                font-size: 13px;
                font-weight: 600;
                cursor: pointer;
                text-decoration: none;
                white-space: nowrap;
            }

            .logs-action-link svg {
                width: 14px;
                height: 14px;
            }

            .logs-action-link.retry-link {
                color: var(--ch-text);
                margin-right: 12px;
            }

            .logs-action-link.details-link {
                color: var(--ch-primary);
            }

            .logs-action-link.details-link:hover {
                color: var(--ch-primary-dark);
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
                                <i data-lucide="layout-grid"></i> Overview
                            </a>
                        </li>
                        <li class="nav-item">
                            <a class="nav-link" data-tab="sync-ops" href="#sync-ops">
                                <i data-lucide="globe"></i> Manual Sync Operations
                            </a>
                        </li>
                        <li class="nav-item">
                            <a class="nav-link" data-tab="last-sync" href="#last-sync">
                                <i data-lucide="clock"></i> Last Sync Attempts
                            </a>
                        </li>
                        <li class="nav-item">
                            <a class="nav-link" data-tab="logs" href="#logs">
                                <i data-lucide="file-text"></i> Sync Logs
                            </a>
                        </li>
                        <li class="nav-item">
                            <a class="nav-link" data-tab="analytics" href="#analytics">
                                <i data-lucide="bar-chart-2"></i> Analytics
                            </a>
                        </li>
                        <li class="nav-item">
                            <a class="nav-link" data-tab="entities" href="#entities">
                                <i data-lucide="sliders-horizontal"></i> Entity Status
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
        this.create_lucide_icons();
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
                <div class="xero-connection-left">
                    <div class="xero-connection-icon">
                        <i data-lucide="globe"></i>
                    </div>
                    <div class="xero-connection-title">
                        Xero Connection
                        <span class="badge badge-${data.connection.connected ? 'success' : 'danger'}">
                            ${data.connection.connected ? '✓ Connected' : 'Disconnected'}
                        </span>
                    </div>
                </div>
                <div class="xero-connection-meta">
                    <div class="xero-connection-meta-item">
                        <label>Tenant</label>
                        <span>${data.connection.tenant_name || '—'}</span>
                    </div>
                    <div class="xero-connection-meta-item">
                        <label>Sync Enabled</label>
                        <span style="color:${data.connection.sync_enabled ? 'var(--ch-success)' : 'var(--ch-warning)'};">
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
                    <div class="stat-text">
                        <div class="stat-label-top">Successful Syncs (24h)</div>
                        <div class="stat-value">${data.sync_stats.overall.find(s => s.status === 'Success')?.count || 0}</div>
                    </div>
                    <div class="stat-icon-circle icon-success">
                        <i data-lucide="check-circle"></i>
                    </div>
                </div>
                <div class="overview-stat-card">
                    <div class="stat-text">
                        <div class="stat-label-top">Failed Syncs (24h)</div>
                        <div class="stat-value">${data.sync_stats.overall.find(s => s.status === 'Error')?.count || 0}</div>
                    </div>
                    <div class="stat-icon-circle icon-danger">
                        <i data-lucide="alert-circle"></i>
                    </div>
                </div>
                <div class="overview-stat-card">
                    <div class="stat-text">
                        <div class="stat-label-top">Active Jobs</div>
                        <div class="stat-value">${data.active_jobs.length}</div>
                    </div>
                    <div class="stat-icon-circle icon-info">
                        <i data-lucide="clock"></i>
                    </div>
                </div>
                <div class="overview-stat-card">
                    <div class="stat-text">
                        <div class="stat-label-top">Total Synced Entities</div>
                        <div class="stat-value">${data.entity_status.reduce((sum, e) => sum + e.synced, 0)}</div>
                    </div>
                    <div class="stat-icon-circle icon-primary">
                        <i data-lucide="database"></i>
                    </div>
                </div>
            </div>

            <!-- Recent Errors & Active Jobs -->
            <div class="row">
                <div class="col-md-7">
                    <div class="errors-card">
                        <div class="section-card-header">
                            <i data-lucide="alert-triangle"></i> Recent Errors
                        </div>
                        ${data.recent_errors.errors.length > 0 ?
                            data.recent_errors.errors.slice(0, 5).map(error => `
                                <div class="error-list-item">
                                    <div class="error-dot"></div>
                                    <div class="error-top-row">
                                        <span class="error-doc-title">${error.erpnext_doc_type} ${error.erpnext_doc_name}</span>
                                        <span class="error-time">${frappe.datetime.comment_when(error.timestamp)}</span>
                                    </div>
                                    <div class="error-message">${error.message}</div>
                                    <span class="badge badge-secondary">${error.category}</span>
                                </div>
                            `).join('') :
                            '<div class="empty-state"><i data-lucide="check-circle"></i><p>No recent errors</p></div>'
                        }
                    </div>
                </div>
                <div class="col-md-5">
                    <div class="jobs-card">
                        <div class="section-card-header">
                            <i data-lucide="list-filter"></i> Active Jobs
                        </div>
                        ${data.active_jobs.length > 0 ?
                            data.active_jobs.slice(0, 5).map(job => `
                                <div class="error-list-item">
                                    <div class="error-top-row">
                                        <span class="error-doc-title">${job.job_name}</span>
                                        <span class="badge badge-${this.get_job_status_color(job.status)}">${job.status}</span>
                                    </div>
                                    <div class="error-message">
                                        Started: ${frappe.datetime.comment_when(job.started_at || job.creation)}
                                        ${job.duration ? `· ${Math.round(job.duration / 60)} min` : ''}
                                    </div>
                                </div>
                            `).join('') :
                            '<div class="empty-state"><i data-lucide="list-filter"></i><p>No active jobs</p></div>'
                        }
                    </div>
                </div>
            </div>
        `;

        $(this.wrapper).find('#overview').html(overview_html);
        this.create_lucide_icons();
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
            <!-- Section Header Card -->
            <div class="xero-sync-header-modern">
                <div>
                    <div class="xero-sync-title">Manual Sync Operations</div>
                    <p class="xero-sync-subtitle">Trigger synchronization between ERPNext and Xero for specific entity types</p>
                </div>
                <div class="xero-sync-ready-badge">
                    <i data-lucide="check-circle"></i> Ready
                </div>
            </div>

            <!-- ERPNext → Xero Section -->
            <div class="sync-direction-card ${!sync_to_xero_enabled ? 'disabled-section' : ''}">
                ${!sync_to_xero_enabled ? `
                    <div class="alert alert-warning mb-3" style="border-radius:var(--ch-radius-md);">
                        <strong><i data-lucide="alert-triangle" style="width:14px;height:14px;display:inline;"></i> Sync TO Xero is Disabled</strong>
                        <p class="mb-0" style="margin-top:4px;font-size:13px;">
                            Go to <a href="/app/xero-settings" target="_blank">Xero Settings</a> and enable "Sync TO Xero"
                        </p>
                    </div>
                ` : ''}
                <div class="sync-direction-header">
                    <div class="sync-direction-icon to-xero">
                        <i data-lucide="arrow-right"></i>
                    </div>
                    <div class="sync-direction-info">
                        <h3>ERPNext → Xero</h3>
                        <p>Push data from ERPNext to Xero</p>
                    </div>
                </div>
                <div class="sync-chips-grid">
                    ${this.render_sync_chip_buttons([
                        { name: 'Sales Invoice', lucide: 'file-text', color: 'blue' },
                        { name: 'Purchase Invoice', lucide: 'file-minus', color: 'indigo' },
                        { name: 'Payment Entry', lucide: 'credit-card', color: 'green' },
                        { name: 'Journal Entry', lucide: 'book-open', color: 'orange' },
                        { name: 'Customer', lucide: 'users', color: 'purple' },
                        { name: 'Supplier', lucide: 'truck', color: 'red' },
                        { name: 'Item', lucide: 'package', color: 'teal' },
                        { name: 'Quotation', lucide: 'file-check', color: 'violet' },
                        { name: 'Bank Transaction', lucide: 'landmark', color: 'gray' }
                    ], sync_to_xero_enabled)}
                </div>
            </div>

            <!-- Xero → ERPNext Section -->
            <div class="sync-direction-card ${!sync_from_xero_enabled ? 'disabled-section' : ''}">
                ${!sync_from_xero_enabled ? `
                    <div class="alert alert-warning mb-3" style="border-radius:var(--ch-radius-md);">
                        <strong><i data-lucide="alert-triangle" style="width:14px;height:14px;display:inline;"></i> Sync FROM Xero is Disabled</strong>
                        <p class="mb-0" style="margin-top:4px;font-size:13px;">
                            Go to <a href="/app/xero-settings" target="_blank">Xero Settings</a> and enable "Sync FROM Xero"
                        </p>
                    </div>
                ` : ''}
                <div class="sync-direction-header">
                    <div class="sync-direction-icon from-xero">
                        <i data-lucide="arrow-left"></i>
                    </div>
                    <div class="sync-direction-info">
                        <h3>Xero → ERPNext</h3>
                        <p>Pull data from Xero to ERPNext</p>
                    </div>
                </div>
                <div class="sync-chips-grid">
                    ${this.render_sync_chip_buttons([
                        { name: 'Xero Contacts', lucide: 'contact', color: 'indigo' },
                        { name: 'Xero Accounts', lucide: 'building-2', color: 'green' },
                        { name: 'Xero Items', lucide: 'package', color: 'teal' },
                        { name: 'Xero Invoices', lucide: 'file-text', color: 'blue' },
                        { name: 'Xero Credit Notes', lucide: 'file-minus', color: 'crimson' },
                        { name: 'Xero Payments', lucide: 'wallet', color: 'green' },
                        { name: 'Xero Manual Journals', lucide: 'book-open', color: 'orange' },
                        { name: 'Xero Quotes', lucide: 'file-check', color: 'violet' },
                        { name: 'Xero Bank Transactions', lucide: 'landmark', color: 'gray' },
                        { name: 'Xero Purchase Orders', lucide: 'shopping-cart', color: 'red' }
                    ], sync_from_xero_enabled)}
                </div>
            </div>

            <!-- Bulk Operations -->
            <div class="bulk-ops-card">
                <div class="bulk-ops-header">
                    <i data-lucide="refresh-cw"></i> Bulk Operations
                </div>
                <div class="bulk-ops-row">
                    <button class="bulk-btn bulk-btn-danger" onclick="dashboard.bulk_retry_failed()">
                        <i data-lucide="alert-triangle"></i> Retry All Failed Jobs
                    </button>
                    <button class="bulk-btn bulk-btn-primary" onclick="dashboard.sync_all_entities()">
                        <i data-lucide="refresh-cw"></i> Sync All Entities
                    </button>
                    <button class="bulk-btn bulk-btn-ghost" onclick="dashboard.clear_old_logs()">
                        <i data-lucide="trash-2"></i> Clear Old Logs
                    </button>
                </div>
            </div>

            <!-- Sync Queue Status -->
            <div class="bulk-ops-card">
                <div class="queue-section-header">
                    <i data-lucide="list-filter"></i> Sync Queue Status
                </div>
                <div id="queue-status">Loading queue status...</div>
            </div>
        `;

        $(this.wrapper).find('#sync-ops').html(sync_ops_html);
        this.create_lucide_icons();
        this.load_queue_status();
    }

    render_sync_chip_buttons(entities, enabled = true) {
        return entities.map(entity => `
            <button class="sync-chip-btn ${!enabled ? 'disabled' : ''}"
                    data-entity="${entity.name}"
                    onclick="${enabled ? `dashboard.trigger_sync('${entity.name}')` : 'return false;'}"
                    ${!enabled ? 'disabled' : ''}>
                <i data-lucide="${entity.lucide}" class="chip-icon chip-icon-${entity.color}"></i>
                <span class="sync-chip-label">${entity.name}</span>
            </button>
        `).join('');
    }

    render_sync_buttons(entities) {
        return entities.map(entity => `
            <button class="btn btn-outline-primary btn-sm mb-2 mr-2 sync-btn"
                    data-entity="${entity}" onclick="dashboard.trigger_sync('${entity}')">
                <i data-lucide="refresh-cw" style="width:12px;height:12px;display:inline;"></i> ${entity}
            </button>
        `).join('');
    }

    render_xero_sync_buttons(entities, enabled = true) {
        // Legacy method kept for compatibility — delegates to chip buttons
        return this.render_sync_chip_buttons(entities.map(e => ({
            name: e.name,
            lucide: 'circle',
            color: 'blue'
        })), enabled);
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
            <!-- Section Header -->
            <div class="logs-header-card">
                <i data-lucide="bar-chart-2"></i> Analytics
            </div>

            <!-- Performance Metrics -->
            <div class="overview-stats-grid" style="margin-bottom:24px;">
                <div class="overview-stat-card">
                    <div class="stat-text">
                        <div class="stat-label-top">Total Operations</div>
                        <div class="stat-value">${data.performance.total_operations || 0}</div>
                    </div>
                    <div class="stat-icon-circle icon-primary">
                        <i data-lucide="activity"></i>
                    </div>
                </div>
                <div class="overview-stat-card">
                    <div class="stat-text">
                        <div class="stat-label-top">Avg Processing Time</div>
                        <div class="stat-value">${Math.round(data.performance.avg_processing_time || 0)}s</div>
                    </div>
                    <div class="stat-icon-circle icon-info">
                        <i data-lucide="timer"></i>
                    </div>
                </div>
                <div class="overview-stat-card">
                    <div class="stat-text">
                        <div class="stat-label-top">Entity Types</div>
                        <div class="stat-value">${data.performance.entity_types_synced || 0}</div>
                    </div>
                    <div class="stat-icon-circle icon-success">
                        <i data-lucide="layers"></i>
                    </div>
                </div>
                <div class="overview-stat-card">
                    <div class="stat-text">
                        <div class="stat-label-top">Success Rate</div>
                        <div class="stat-value" style="color:${success_rate < 50 ? 'var(--ch-danger-alt)' : 'var(--ch-text)'};">${success_rate}%</div>
                    </div>
                    <div class="stat-icon-circle ${success_rate < 50 ? 'icon-danger' : 'icon-success'}">
                        <i data-lucide="percent"></i>
                    </div>
                </div>
            </div>

            <!-- Entity Performance -->
            <div class="logs-table-card">
                <div class="section-card-header">
                    <i data-lucide="bar-chart-2"></i> Entity Performance
                </div>
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
        `;

        $(this.wrapper).find('#analytics').html(analytics_html);
        this.create_lucide_icons();
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
            <!-- Section Header -->
            <div class="logs-header-card">
                <i data-lucide="sliders-horizontal"></i> Entity Status
            </div>

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
                                <i data-lucide="refresh-cw" style="width:12px;height:12px;display:inline;"></i> Sync Now
                            </a>
                        </div>
                    </div>
                `).join('')}
            </div>
        `;

        $(this.wrapper).find('#entities').html(entity_html);
        this.create_lucide_icons();
    }

    load_logs() {
        const logs_html = `
            <!-- Section Header -->
            <div class="logs-header-card">
                <i data-lucide="file-text"></i> Sync Logs
            </div>

            <!-- Filters -->
            <div class="logs-filters-card">
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
                <button class="logs-filter-btn" onclick="dashboard.apply_log_filters()">
                    <i data-lucide="filter"></i> Filter
                </button>
            </div>

            <!-- Logs Table -->
            <div class="logs-table-card">
                <div id="logs-table">Loading logs...</div>
            </div>
        `;

        $(this.wrapper).find('#logs').html(logs_html);
        this.create_lucide_icons();
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
                                <td style="max-width: 400px;" title="${log.message}">
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
                                <td style="white-space:nowrap;">${frappe.datetime.comment_when(log.timestamp)}</td>
                                <td style="white-space:nowrap;">
                                    ${log.status === 'Error' ?
                                        `<a class="logs-action-link retry-link" data-log-name="${log.name}" onclick="dashboard.retry_job('${log.name}')">
                                            Retry
                                        </a>` :
                                        ''
                                    }
                                    <a class="logs-action-link details-link" onclick="dashboard.view_log_details('${log.name}')">
                                        <i data-lucide="eye"></i> Details
                                    </a>
                                </td>
                            </tr>
                        `).join('')}
                    </tbody>
                </table>
            </div>

            ${data.has_more ?
                `<div style="text-align:center;padding:16px;">
                    <button class="btn btn-outline-primary btn-sm" onclick="dashboard.load_more_logs()">
                        Load More
                    </button>
                </div>` :
                ''
            }
        `;

        $(this.wrapper).find('#logs-table').html(table_html);
        this.create_lucide_icons();
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
                btn.find('.sync-chip-label, .sync-button-title').text(`Syncing ${entity}...`);
                
                frappe.call({
                    method: 'xero.xero.page.xero_sync_dashboard.xero_sync_dashboard.trigger_manual_sync',
                    args: { entity_type: entity },
                    callback: (r) => {
                        // Restore button
                        btn.prop('disabled', false).css('opacity', '1');
                        btn.html(original_html);
                        this.create_lucide_icons();
                        
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
        // Calculate totals across all queues
        const totals = data.queues.reduce((acc, q) => ({
            pending: acc.pending + (q.pending || 0),
            running: acc.running + (q.running || 0),
            completed: acc.completed + (q.completed || 0),
            failed: acc.failed + (q.failed || 0)
        }), { pending: 0, running: 0, completed: 0, failed: 0 });

        const queue_html = `
            <div class="queue-stats-grid">
                <div class="queue-stat-card">
                    <div class="queue-stat-icon icon-queued">
                        <i data-lucide="clock"></i>
                    </div>
                    <div class="queue-stat-value">${totals.pending}</div>
                    <div class="queue-stat-label">Queued</div>
                </div>
                <div class="queue-stat-card">
                    <div class="queue-stat-icon icon-processing">
                        <i data-lucide="refresh-cw"></i>
                    </div>
                    <div class="queue-stat-value">${totals.running}</div>
                    <div class="queue-stat-label">Processing</div>
                </div>
                <div class="queue-stat-card">
                    <div class="queue-stat-icon icon-completed">
                        <i data-lucide="check-circle"></i>
                    </div>
                    <div class="queue-stat-value">${totals.completed}</div>
                    <div class="queue-stat-label">Completed</div>
                </div>
                <div class="queue-stat-card">
                    <div class="queue-stat-icon icon-failed">
                        <i data-lucide="x-circle"></i>
                    </div>
                    <div class="queue-stat-value">${totals.failed}</div>
                    <div class="queue-stat-label">Failed</div>
                </div>
            </div>
        `;

        $(this.wrapper).find('#queue-status').html(queue_html);
        this.create_lucide_icons();
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
            <!-- Section Header -->
            <div class="logs-header-card">
                <i data-lucide="clock"></i> Last Sync Attempts
            </div>

            <!-- Summary Stats -->
            <div class="overview-stats-grid" style="grid-template-columns: repeat(6, 1fr); margin-bottom: 20px;">
                <div class="overview-stat-card">
                    <div class="stat-text">
                        <div class="stat-label-top">Total</div>
                        <div class="stat-value" style="font-size:24px;">${data.total_attempts || 0}</div>
                    </div>
                </div>
                <div class="overview-stat-card">
                    <div class="stat-text">
                        <div class="stat-label-top">Successful</div>
                        <div class="stat-value" style="font-size:24px;color:var(--ch-success);">${data.successful_attempts || 0}</div>
                    </div>
                </div>
                <div class="overview-stat-card">
                    <div class="stat-text">
                        <div class="stat-label-top">Failed</div>
                        <div class="stat-value" style="font-size:24px;color:var(--ch-danger-alt);">${data.failed_attempts || 0}</div>
                    </div>
                </div>
                <div class="overview-stat-card">
                    <div class="stat-text">
                        <div class="stat-label-top">Partial</div>
                        <div class="stat-value" style="font-size:24px;color:var(--ch-warning);">${data.partial_success_attempts || 0}</div>
                    </div>
                </div>
                <div class="overview-stat-card">
                    <div class="stat-text">
                        <div class="stat-label-top">Warnings</div>
                        <div class="stat-value" style="font-size:24px;color:var(--ch-warning);">${data.warning_only_attempts || 0}</div>
                    </div>
                </div>
                <div class="overview-stat-card">
                    <div class="stat-text">
                        <div class="stat-label-top">With Warnings</div>
                        <div class="stat-value" style="font-size:24px;color:var(--ch-primary);">${data.success_with_warnings_attempts || 0}</div>
                    </div>
                </div>
            </div>

            <!-- Sync Attempts List -->
            <div>
                ${data.sync_attempts && data.sync_attempts.length > 0 ?
                    data.sync_attempts.map(attempt => `
                        <div class="sync-attempt-block attempt-${this.get_sync_attempt_status_class(attempt.overall_status)}">
                            <div class="sync-attempt-header">
                                <div style="display:flex;align-items:center;gap:10px;">
                                    <i data-lucide="${this.get_sync_direction_lucide(attempt.sync_direction)}"></i>
                                    <div>
                                        <div style="font-weight:600;">${attempt.sync_label ? attempt.sync_label : attempt.sync_direction}</div>
                                        ${attempt.sync_label ? `<div style="font-size:11px;color:var(--ch-text-muted);font-weight:400;">${attempt.sync_direction}</div>` : ''}
                                    </div>
                                </div>
                                <div style="display:flex;align-items:center;gap:12px;">
                                    <span style="font-size:12px;color:var(--ch-text-muted);">${frappe.datetime.str_to_user(attempt.sync_time)}</span>
                                    <span class="badge badge-${this.get_sync_attempt_color(attempt.overall_status)}">${attempt.overall_status}</span>
                                </div>
                            </div>
                            <div class="sync-attempt-body">
                                <div class="row mb-3">
                                    <div class="col-md-12">
                                        <strong style="font-size:12px;color:var(--ch-text-muted);text-transform:uppercase;letter-spacing:0.06em;">Entities Synced:</strong>
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
                                            <div style="background:var(--ch-danger-bg);border:1px solid var(--ch-danger-border);border-radius:var(--ch-radius-md);padding:14px 16px;">
                                                <h6 style="margin:0 0 10px 0;font-size:13px;display:flex;align-items:center;gap:6px;color:var(--ch-danger-alt);">
                                                    <i data-lucide="alert-triangle" style="width:14px;height:14px;"></i> Sync Issues Detected
                                                </h6>
                                                <div class="table-responsive">
                                                    <table class="table table-sm mb-0">
                                                        <thead>
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
                                                                    <td><span class="badge badge-danger">${failure.count}</span></td>
                                                                    <td style="max-width:200px;" title="${failure.affected_docs || ''}">
                                                                        <small>${failure.affected_docs || '-'}</small>
                                                                    </td>
                                                                    <td style="max-width:300px;" title="${failure.example_message || ''}">
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
                                            <h6 style="font-size:12px;color:var(--ch-text-muted);text-transform:uppercase;letter-spacing:0.06em;margin-bottom:10px;display:flex;align-items:center;gap:6px;">
                                                <i data-lucide="lightbulb" style="width:14px;height:14px;"></i> Recommended Actions
                                            </h6>
                                            ${attempt.actionable_recommendations.map(rec => `
                                                <div style="background:${rec.severity === 'high' ? 'var(--ch-danger-bg)' : rec.severity === 'medium' ? 'var(--ch-warning-bg)' : 'var(--ch-info-bg)'};border:1px solid ${rec.severity === 'high' ? 'var(--ch-danger-border)' : rec.severity === 'medium' ? 'var(--ch-warning-border)' : 'rgba(91,138,196,0.2)'};border-radius:var(--ch-radius-md);padding:14px 16px;margin-bottom:10px;">
                                                    <h6 style="margin:0 0 4px 0;font-size:13px;font-weight:600;">${rec.title}</h6>
                                                    <p style="margin:0 0 4px 0;font-size:13px;color:var(--ch-text-muted);">${rec.message}</p>
                                                    <p style="margin:0 0 10px 0;font-size:13px;"><strong>Action:</strong> ${rec.action}</p>
                                                    <div style="display:flex;gap:8px;flex-wrap:wrap;">
                                                        ${rec.type === 'account_mapping' ? `
                                                            <button class="btn btn-sm btn-primary" onclick="dashboard.open_quick_mapping_dialog()">
                                                                Map Now
                                                            </button>
                                                        ` : ''}
                                                        ${rec.action_button ? `
                                                            <button class="btn btn-sm btn-outline-${rec.severity === 'high' ? 'danger' : 'warning'}"
                                                                    onclick="${rec.action_button.route ? `frappe.set_route('${rec.action_button.route}')` : `dashboard.trigger_sync('${rec.action_button.entity}')`}">
                                                                ${rec.action_button.label}
                                                            </button>
                                                        ` : ''}
                                                        ${rec.secondary_button ? `
                                                            <button class="btn btn-sm btn-outline-primary"
                                                                    onclick="dashboard.view_filtered_logs(${JSON.stringify(rec.secondary_button.filter).replace(/"/g, '&quot;')})">
                                                                View Logs
                                                            </button>
                                                        ` : ''}
                                                    </div>
                                                </div>
                                            `).join('')}
                                        </div>
                                    </div>
                                ` : ''}
                                
                                <!-- Detailed Item Status -->
                                <div class="table-responsive">
                                    <table class="table table-sm">
                                        <thead>
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
                                                    <tr>
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
                                                        <td style="max-width:300px;" title="${item.message || ''}">
                                                            ${item.status === 'Error' ? (item.message || 'No error message') : '-'}
                                                        </td>
                                                        <td style="white-space:nowrap;">
                                                            <small>${frappe.datetime.comment_when(item.timestamp)}</small>
                                                        </td>
                                                        <td style="white-space:nowrap;">
                                                            ${item.status === 'Error' && item.log_name ?
                                                                `<a class="logs-action-link retry-link" onclick="dashboard.retry_job('${item.log_name}')">Retry</a>` :
                                                                ''
                                                            }
                                                            ${item.log_name ?
                                                                `<a class="logs-action-link details-link" onclick="dashboard.view_log_details('${item.log_name}')">
                                                                    <i data-lucide="eye"></i> Details
                                                                </a>` :
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
                                <div style="display:flex;justify-content:space-between;align-items:center;margin-top:12px;padding-top:12px;border-top:1px solid var(--ch-border);">
                                    <div>
                                        <span class="badge badge-success" style="margin-right:4px;">${attempt.success_count || 0} Success</span>
                                        <span class="badge badge-danger" style="margin-right:4px;">${attempt.error_count || 0} Failed</span>
                                        <span class="badge badge-warning" style="margin-right:4px;">${attempt.warning_count || 0} Warnings</span>
                                        ${attempt.skipped_count > 0 ? `<span class="badge badge-secondary">${attempt.skipped_count} Skipped</span>` : ''}
                                    </div>
                                    <small class="text-muted">Duration: ${attempt.duration ? `${attempt.duration}s` : 'N/A'}</small>
                                </div>
                            </div>
                        </div>
                    `).join('') :
                    '<div class="empty-state" style="background:var(--ch-surface);border:1px solid var(--ch-border);border-radius:var(--ch-radius-lg);padding:40px;"><i data-lucide="clock"></i><p>No sync attempts found in the last 7 days.</p></div>'
                }
            </div>
        `;

        $(this.wrapper).find('#last-sync').html(last_sync_html);
        this.create_lucide_icons();
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

    get_sync_direction_lucide(direction) {
        if (direction && direction.includes('→')) {
            if (direction.includes('ERPNext → Xero')) return 'arrow-right';
            if (direction.includes('Xero → ERPNext')) return 'arrow-left';
            if (direction.includes('Both')) return 'arrow-left-right';
        }
        return 'refresh-cw';
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
                                <h5 class="mb-0"><i data-lucide="clock" style="width:16px;height:16px;display:inline;"></i> Average Sync Latency by Entity (Last 24h)</h5>
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
                                <h5 class="mb-0"><i data-lucide="hourglass" style="width:16px;height:16px;display:inline;"></i> Slowest Operations (Last 24h)</h5>
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
                                <h5 class="mb-0"><i data-lucide="layers" style="width:16px;height:16px;display:inline;"></i> Queue Depth by Entity</h5>
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
            <div style="background:var(--ch-danger-bg);border:1px solid var(--ch-danger-border);border-radius:var(--ch-radius-lg);padding:24px;">
                <h5 style="color:var(--ch-danger-alt);margin:0 0 8px 0;display:flex;align-items:center;gap:8px;">
                    <i data-lucide="alert-circle" style="width:18px;height:18px;"></i> ${title}
                </h5>
                <p style="color:var(--ch-text-muted);margin:0 0 16px 0;">${message || 'An unexpected error occurred.'}</p>
                <button class="bulk-btn bulk-btn-danger" onclick="dashboard.refresh_current_tab()">
                    <i data-lucide="refresh-cw"></i> Retry
                </button>
            </div>
        `);
        this.create_lucide_icons();
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
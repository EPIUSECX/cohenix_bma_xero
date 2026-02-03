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
        // Add comprehensive CSS styling
        $(`<style>
            /* Xero Professional Theme - Light/Dark Mode Support */
            :root {
                --xero-primary: #13B5EA;
                --xero-primary-dark: #0F9BC7;
                --xero-secondary: #034C8C;
                --xero-success: #00A86B;
                --xero-warning: #F7931E;
                --xero-danger: #E74C3C;
                --xero-info: #3498DB;
                --xero-light: #F8F9FA;
                --xero-dark: #2C3E50;
                --xero-border: #E1E5E9;
                --xero-text: #2C3E50;
                --xero-text-muted: #6C757D;
                --xero-bg: #FFFFFF;
                --xero-bg-alt: #F8F9FA;
                --xero-shadow: rgba(0, 0, 0, 0.1);
            }

            /* Dark theme variables */
            html[data-theme-mode="dark"] {
                --xero-primary: #13B5EA;
                --xero-primary-dark: #0F9BC7;
                --xero-secondary: #4A90E2;
                --xero-success: #00A86B;
                --xero-warning: #F7931E;
                --xero-danger: #E74C3C;
                --xero-info: #3498DB;
                --xero-light: #34495E;
                --xero-dark: #ECF0F1;
                --xero-border: #34495E;
                --xero-text: #ECF0F1;
                --xero-text-muted: #BDC3C7;
                --xero-bg: #2C3E50;
                --xero-bg-alt: #34495E;
                --xero-shadow: rgba(0, 0, 0, 0.3);
            }

            .xero-dashboard-container {
                padding: 20px;
                background: var(--xero-bg-alt);
                min-height: calc(100vh - 150px);
                color: var(--xero-text);
            }

            .xero-dashboard-tabs {
                background: var(--xero-bg);
                border-radius: 8px;
                box-shadow: 0 2px 8px var(--xero-shadow);
                margin-bottom: 20px;
                border: 1px solid var(--xero-border);
                position: relative;
            }

            .xero-dashboard-tabs::after {
                content: '';
                position: absolute;
                top: 50%;
                right: 20px;
                width: 250px;
                height: 60px;
                background-image: url('/assets/xero/images/xero-logo.png');
                background-size: contain;
                background-repeat: no-repeat;
                background-position: center;
                opacity: 0.9;
                transform: translateY(-50%);
            }

            .xero-dashboard-content {
                background: var(--xero-bg);
                border-radius: 8px;
                box-shadow: 0 2px 8px var(--xero-shadow);
                padding: 24px;
                min-height: 500px;
                border: 1px solid var(--xero-border);
            }

            .tab-content {
                display: none;
            }

            .tab-content.active {
                display: block;
            }

            .nav-tabs {
                border-bottom: 2px solid var(--xero-border);
                padding: 0 20px;
            }

            .nav-tabs .nav-link {
                color: var(--xero-text-muted);
                border: none;
                padding: 16px 20px;
                font-weight: 500;
                transition: all 0.2s ease;
            }

            .nav-tabs .nav-link.active {
                background-color: var(--xero-primary) !important;
                color: white !important;
                border-radius: 6px 6px 0 0;
                border: none !important;
                position: relative;
            }

            .nav-tabs .nav-link:hover:not(.active) {
                color: var(--xero-primary);
                background-color: transparent;
            }

            .xero-loading-overlay {
                position: absolute;
                top: 0;
                left: 0;
                right: 0;
                bottom: 0;
                background: var(--xero-bg);
                opacity: 0.95;
                display: flex;
                align-items: center;
                justify-content: center;
                z-index: 1000;
                border-radius: 8px;
            }

            .loading-content {
                text-align: center;
                color: var(--xero-text);
            }

            .metric-card, .entity-card, .card {
                border: 1px solid var(--xero-border);
                border-radius: 8px;
                margin-bottom: 20px;
                background: var(--xero-bg);
                box-shadow: 0 2px 4px var(--xero-shadow);
            }

            .card-header {
                background: var(--xero-bg-alt);
                border-bottom: 1px solid var(--xero-border);
                color: var(--xero-text);
            }

            .card-body {
                background: var(--xero-bg);
                color: var(--xero-text);
            }

            .error-item, .job-item {
                border-left: 4px solid var(--xero-danger);
                padding: 12px;
                margin-bottom: 12px;
                background: var(--xero-bg-alt);
                border-radius: 0 6px 6px 0;
                border: 1px solid var(--xero-border);
                border-left: 4px solid var(--xero-danger);
            }

            .job-item {
                border-left-color: var(--xero-info);
            }

            /* Professional Xero-themed Manual Sync Operations */
            .xero-sync-header {
                background: var(--xero-primary);
                color: white;
                padding: 20px 24px;
                border-radius: 8px 8px 0 0;
                position: relative;
            }

            .xero-sync-title {
                font-size: 18px;
                font-weight: 700;
                margin: 0;
                display: flex;
                align-items: center;
                gap: 12px;
                color: white !important;
            }

            .xero-sync-subtitle {
                font-size: 14px;
                opacity: 0.95;
                margin: 8px 0 0 0;
                color: white !important;
                font-weight: 500;
            }

            .xero-sync-status {
                position: absolute;
                top: 20px;
                right: 24px;
                background: rgba(255, 255, 255, 0.2);
                padding: 6px 12px;
                border-radius: 20px;
                font-size: 12px;
                font-weight: 500;
            }

            .xero-sync-body {
                padding: 32px 24px;
                background: var(--xero-bg);
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
                top: 0;
                left: 0;
                right: 0;
                bottom: 0;
                background: rgba(128, 128, 128, 0.1);
                border-radius: 8px;
                z-index: 1;
            }

            .sync-direction-header {
                display: flex;
                align-items: center;
                margin-bottom: 20px;
                padding-bottom: 12px;
                border-bottom: 2px solid var(--xero-border);
            }

            .sync-direction-icon {
                width: 40px;
                height: 40px;
                border-radius: 8px;
                display: flex;
                align-items: center;
                justify-content: center;
                margin-right: 16px;
                font-size: 18px;
                color: white;
            }

            .sync-direction-icon.to-xero {
                background: var(--xero-secondary);
            }

            .sync-direction-icon.from-xero {
                background: var(--xero-success);
            }

            .sync-direction-info h3 {
                margin: 0;
                font-size: 16px;
                font-weight: 600;
                color: var(--xero-text);
            }

            .sync-direction-info p {
                margin: 4px 0 0 0;
                font-size: 13px;
                color: var(--xero-text-muted);
            }

            .sync-buttons-grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
                gap: 16px;
            }

            .xero-sync-button {
                display: flex;
                align-items: center;
                padding: 16px 20px;
                background: var(--xero-bg);
                border: 2px solid var(--xero-border);
                border-radius: 8px;
                text-decoration: none;
                color: var(--xero-text);
                font-weight: 500;
                cursor: pointer;
                transition: all 0.2s ease;
                position: relative;
            }

            .xero-sync-button:hover {
                border-color: var(--xero-primary);
                background: var(--xero-bg-alt);
                text-decoration: none;
                color: var(--xero-text);
            }

            .xero-sync-button:active {
                transform: translateY(1px);
            }

            .sync-button-icon {
                width: 36px;
                height: 36px;
                border-radius: 6px;
                display: flex;
                align-items: center;
                justify-content: center;
                margin-right: 16px;
                font-size: 18px;
                color: white !important;
                flex-shrink: 0;
                position: relative;
            }

            .sync-button-icon i {
                color: white !important;
                font-size: 18px !important;
                font-weight: 900 !important;
                text-shadow: 0 1px 2px rgba(0,0,0,0.3);
                z-index: 2;
                position: relative;
            }

            .sync-button-icon::before {
                content: '';
                position: absolute;
                top: 0;
                left: 0;
                right: 0;
                bottom: 0;
                border-radius: 6px;
                z-index: 1;
            }

            .sync-button-text {
                flex: 1;
            }

            .sync-button-title {
                font-size: 14px;
                font-weight: 600;
                margin: 0;
                color: var(--xero-text);
            }

            /* Entity-specific colors matching Xero's design */
            .icon-sales-invoice { background: var(--xero-primary); }
            .icon-purchase-invoice { background: var(--xero-secondary); }
            .icon-payment-entry { background: var(--xero-success); }
            .icon-journal-entry { background: var(--xero-warning); }
            .icon-customer { background: #8E44AD; }
            .icon-supplier { background: #E67E22; }
            .icon-item { background: #16A085; }
            .icon-quotation { background: #9B59B6; }
            .icon-bank-transaction { background: var(--xero-dark); }
            .icon-sync-accounts { background: var(--xero-success); }
            .icon-sync-contacts { background: var(--xero-info); }
            .icon-sync-items { background: var(--xero-warning); }
            .icon-sync-payments { background: var(--xero-primary); }
            .icon-sync-bank-transactions { background: var(--xero-dark); }

            /* Table and other elements theme support */
            .table {
                color: var(--xero-text);
            }

            .table th {
                border-top: 1px solid var(--xero-border);
                border-bottom: 2px solid var(--xero-border);
                background: var(--xero-bg-alt);
                color: var(--xero-text);
            }

            .table td {
                border-top: 1px solid var(--xero-border);
                color: var(--xero-text);
            }

            .badge-primary { background-color: var(--xero-primary); }
            .badge-success { background-color: var(--xero-success); }
            .badge-warning { background-color: var(--xero-warning); }
            .badge-danger { background-color: var(--xero-danger); }
            .badge-info { background-color: var(--xero-info); }

            .btn-primary {
                background-color: var(--xero-primary);
                border-color: var(--xero-primary);
            }

            .btn-primary:hover {
                background-color: var(--xero-primary-dark);
                border-color: var(--xero-primary-dark);
            }

            .progress-bar {
                background-color: var(--xero-primary);
            }

            .text-primary { color: var(--xero-primary) !important; }
            .text-success { color: var(--xero-success) !important; }
            .text-warning { color: var(--xero-warning) !important; }
            .text-danger { color: var(--xero-danger) !important; }
            .text-info { color: var(--xero-info) !important; }
            .text-muted { color: var(--xero-text-muted) !important; }

            .bg-primary { background-color: var(--xero-primary) !important; }
            .bg-success { background-color: var(--xero-success) !important; }
            .bg-warning { background-color: var(--xero-warning) !important; }
            .bg-danger { background-color: var(--xero-danger) !important; }
            .bg-info { background-color: var(--xero-info) !important; }

            /* Remove all animations and hover effects for professional look */
            * {
                transition: none !important;
                animation: none !important;
            }

            /* Only keep essential transitions for buttons */
            .xero-sync-button, .btn, .nav-link {
                transition: all 0.2s ease !important;
            }
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
                                <i class="fa fa-sync"></i> Sync Operations
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
                        <li class="nav-item">
                            <a class="nav-link" data-tab="logs" href="#logs">
                                <i class="fa fa-list"></i> Sync Logs
                            </a>
                        </li>
                        <li class="nav-item">
                            <a class="nav-link" data-tab="health" href="#health">
                                <i class="fa fa-heartbeat"></i> Health
                            </a>
                        </li>
                        <li class="nav-item">
                            <a class="nav-link" data-tab="integrity" href="#integrity">
                                <i class="fa fa-check-circle"></i> Integrity
                            </a>
                        </li>
                        <li class="nav-item">
                            <a class="nav-link" data-tab="last-sync" href="#last-sync">
                                <i class="fa fa-history"></i> Last Sync Attempts
                            </a>
                        </li>
                        <li class="nav-item">
                            <a class="nav-link" data-tab="performance" href="#performance">
                                <i class="fa fa-tachometer-alt"></i> Performance
                            </a>
                        </li>
                        <li class="nav-item">
                            <a class="nav-link" data-tab="config" href="#config">
                                <i class="fa fa-cog"></i> Configuration
                            </a>
                        </li>
                    </ul>
                </div>

                <!-- Tab Content -->
                <div class="xero-dashboard-content" style="position: relative;">
                    <div id="overview" class="tab-content active"></div>
                    <div id="sync-ops" class="tab-content"></div>
                    <div id="analytics" class="tab-content"></div>
                    <div id="entities" class="tab-content"></div>
                    <div id="logs" class="tab-content"></div>
                    <div id="health" class="tab-content"></div>
                    <div id="integrity" class="tab-content"></div>
                    <div id="last-sync" class="tab-content"></div>
                    <div id="performance" class="tab-content"></div>
                    <div id="config" class="tab-content"></div>
                    
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
            case 'analytics':
                this.load_analytics();
                break;
            case 'entities':
                this.load_entity_status();
                break;
            case 'logs':
                this.load_logs();
                break;
            case 'health':
                this.load_health_monitoring();
                break;
            case 'integrity':
                this.load_data_integrity();
                break;
            case 'last-sync':
                this.load_last_sync_attempts();
                break;
            case 'performance':
                this.load_performance_metrics();
                break;
            case 'config':
                this.load_configuration();
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
            <div class="row">
                <!-- Connection Status -->
                <div class="col-md-12 mb-4">
                    <div class="card xero-connection-card">
                        <div class="card-header d-flex justify-content-between align-items-center">
                            <h5 class="mb-0">
                                <i class="fa fa-plug"></i> Xero Connection
                            </h5>
                            <span class="badge badge-${data.connection.connected ? 'success' : 'danger'}">
                                ${data.connection.connected ? 'Connected' : 'Disconnected'}
                            </span>
                        </div>
                        <div class="card-body">
                            <div class="row">
                                <div class="col-md-3">
                                    <strong>Tenant:</strong><br>
                                    <span class="text-muted">${data.connection.tenant_name}</span>
                                </div>
                                <div class="col-md-3">
                                    <strong>Sync Enabled:</strong><br>
                                    <span class="badge badge-${data.connection.sync_enabled ? 'success' : 'warning'}">
                                        ${data.connection.sync_enabled ? 'Yes' : 'No'}
                                    </span>
                                </div>
                                <div class="col-md-3">
                                    <strong>Last Sync:</strong><br>
                                    <span class="text-muted">
                                        ${data.connection.last_sync ? frappe.datetime.comment_when(data.connection.last_sync) : 'Never'}
                                    </span>
                                </div>
                                <div class="col-md-3">
                                    <strong>Health Score:</strong><br>
                                    <div class="progress" style="height: 20px;">
                                        <div class="progress-bar bg-${this.get_health_color(data.health.score)}" 
                                             style="width: ${data.health.score}%">
                                            ${data.health.score}%
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Key Metrics -->
                <div class="col-md-12 mb-4">
                    <div class="row">
                        <div class="col-md-3">
                            <div class="card metric-card">
                                <div class="card-body text-center">
                                    <div class="metric-icon text-success">
                                        <i class="fa fa-check-circle fa-2x"></i>
                                    </div>
                                    <h3 class="metric-value">${data.sync_stats.overall.find(s => s.status === 'Success')?.count || 0}</h3>
                                    <p class="metric-label">Successful Syncs (24h)</p>
                                </div>
                            </div>
                        </div>
                        <div class="col-md-3">
                            <div class="card metric-card">
                                <div class="card-body text-center">
                                    <div class="metric-icon text-danger">
                                        <i class="fa fa-exclamation-circle fa-2x"></i>
                                    </div>
                                    <h3 class="metric-value">${data.sync_stats.overall.find(s => s.status === 'Error')?.count || 0}</h3>
                                    <p class="metric-label">Failed Syncs (24h)</p>
                                </div>
                            </div>
                        </div>
                        <div class="col-md-3">
                            <div class="card metric-card">
                                <div class="card-body text-center">
                                    <div class="metric-icon text-info">
                                        <i class="fa fa-clock fa-2x"></i>
                                    </div>
                                    <h3 class="metric-value">${data.active_jobs.length}</h3>
                                    <p class="metric-label">Active Jobs</p>
                                </div>
                            </div>
                        </div>
                        <div class="col-md-3">
                            <div class="card metric-card">
                                <div class="card-body text-center">
                                    <div class="metric-icon text-warning">
                                        <i class="fa fa-database fa-2x"></i>
                                    </div>
                                    <h3 class="metric-value">${data.entity_status.reduce((sum, e) => sum + e.synced, 0)}</h3>
                                    <p class="metric-label">Total Synced Entities</p>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Recent Errors -->
                <div class="col-md-6">
                    <div class="card">
                        <div class="card-header">
                            <h5 class="mb-0"><i class="fa fa-exclamation-triangle"></i> Recent Errors</h5>
                        </div>
                        <div class="card-body">
                            ${data.recent_errors.errors.length > 0 ? 
                                data.recent_errors.errors.slice(0, 5).map(error => `
                                    <div class="error-item mb-2 p-2 border-left border-danger">
                                        <div class="d-flex justify-content-between">
                                            <strong>${error.erpnext_doc_type} ${error.erpnext_doc_name}</strong>
                                            <small class="text-muted">${frappe.datetime.comment_when(error.timestamp)}</small>
                                        </div>
                                        <p class="mb-1 text-muted small">${error.message}</p>
                                        <span class="badge badge-secondary">${error.category}</span>
                                    </div>
                                `).join('') : 
                                '<p class="text-muted">No recent errors</p>'
                            }
                        </div>
                    </div>
                </div>

                <!-- Active Jobs -->
                <div class="col-md-6">
                    <div class="card">
                        <div class="card-header">
                            <h5 class="mb-0"><i class="fa fa-tasks"></i> Active Jobs</h5>
                        </div>
                        <div class="card-body">
                            ${data.active_jobs.length > 0 ? 
                                data.active_jobs.slice(0, 5).map(job => `
                                    <div class="job-item mb-2 p-2 border-left border-info">
                                        <div class="d-flex justify-content-between">
                                            <strong>${job.job_name}</strong>
                                            <span class="badge badge-${this.get_job_status_color(job.status)}">${job.status}</span>
                                        </div>
                                        <small class="text-muted">
                                            Started: ${frappe.datetime.comment_when(job.started_at || job.creation)}
                                            ${job.duration ? `(${Math.round(job.duration / 60)} min)` : ''}
                                        </small>
                                    </div>
                                `).join('') : 
                                '<p class="text-muted">No active jobs</p>'
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
                                        { name: 'Sync Xero Accounts', icon: 'fa-list', class: 'icon-sync-accounts' },
                                        { name: 'Sync Xero Contacts', icon: 'fa-users', class: 'icon-sync-contacts' },
                                        { name: 'Sync Xero Items', icon: 'fa-cubes', class: 'icon-sync-items' },
                                        { name: 'Sync Xero Payments', icon: 'fa-money', class: 'icon-sync-payments' },
                                        { name: 'Sync Xero Bank Transactions', icon: 'fa-exchange', class: 'icon-sync-bank-transactions' }
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
                            <h5 class="mb-0"><i class="fa fa-tasks"></i> Bulk Operations</h5>
                        </div>
                        <div class="card-body">
                            <div class="row">
                                <div class="col-md-4">
                                    <button class="btn btn-warning btn-block" onclick="dashboard.bulk_retry_failed()">
                                        <i class="fa fa-redo"></i> Retry All Failed Jobs
                                    </button>
                                </div>
                                <div class="col-md-4">
                                    <button class="btn btn-info btn-block" onclick="dashboard.sync_all_entities()">
                                        <i class="fa fa-sync-alt"></i> Sync All Entities
                                    </button>
                                </div>
                                <div class="col-md-4">
                                    <button class="btn btn-secondary btn-block" onclick="dashboard.clear_old_logs()">
                                        <i class="fa fa-trash"></i> Clear Old Logs
                                    </button>
                                </div>
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
        const analytics_html = `
            <div class="row">
                <!-- Performance Metrics -->
                <div class="col-md-12 mb-4">
                    <div class="card">
                        <div class="card-header">
                            <h5 class="mb-0"><i class="fa fa-chart-bar"></i> Performance Metrics</h5>
                        </div>
                        <div class="card-body">
                            <div class="row">
                                <div class="col-md-3 text-center">
                                    <h4 class="text-primary">${data.performance.total_operations || 0}</h4>
                                    <p class="text-muted">Total Operations</p>
                                </div>
                                <div class="col-md-3 text-center">
                                    <h4 class="text-success">${Math.round(data.performance.avg_processing_time || 0)}s</h4>
                                    <p class="text-muted">Avg Processing Time</p>
                                </div>
                                <div class="col-md-3 text-center">
                                    <h4 class="text-info">${data.performance.entity_types_synced || 0}</h4>
                                    <p class="text-muted">Entity Types</p>
                                </div>
                                <div class="col-md-3 text-center">
                                    <h4 class="text-warning">${this.calculate_success_rate(data.overall)}%</h4>
                                    <p class="text-muted">Success Rate</p>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Entity Performance -->
                <div class="col-md-12">
                    <div class="card">
                        <div class="card-header">
                            <h5 class="mb-0">Entity Performance</h5>
                        </div>
                        <div class="card-body">
                            <div class="table-responsive">
                                <table class="table table-sm">
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
                                                <td>
                                                    <div class="progress" style="height: 15px;">
                                                        <div class="progress-bar bg-success" 
                                                             style="width: ${entity.success_rate}%">
                                                            ${Math.round(entity.success_rate)}%
                                                        </div>
                                                    </div>
                                                </td>
                                            </tr>
                                        `).join('')}
                                    </tbody>
                                </table>
                            </div>
                        </div>
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
            <div class="row">
                ${entities.map(entity => `
                    <div class="col-md-6 col-lg-4 mb-4">
                        <div class="card entity-card">
                            <div class="card-header d-flex justify-content-between">
                                <h6 class="mb-0">${entity.entity}</h6>
                                <span class="badge badge-info">${entity.total}</span>
                            </div>
                            <div class="card-body">
                                <div class="row text-center">
                                    <div class="col-4">
                                        <div class="text-success">
                                            <strong>${entity.synced}</strong>
                                            <br><small>Synced</small>
                                        </div>
                                    </div>
                                    <div class="col-4">
                                        <div class="text-warning">
                                            <strong>${entity.pending}</strong>
                                            <br><small>Pending</small>
                                        </div>
                                    </div>
                                    <div class="col-4">
                                        <div class="text-danger">
                                            <strong>${entity.errors}</strong>
                                            <br><small>Errors</small>
                                        </div>
                                    </div>
                                </div>
                                <div class="mt-3">
                                    <div class="progress">
                                        <div class="progress-bar bg-success" style="width: ${entity.sync_rate}%">
                                            ${entity.sync_rate}%
                                        </div>
                                    </div>
                                    <small class="text-muted">
                                        Last sync: ${entity.last_sync ? frappe.datetime.comment_when(entity.last_sync) : 'Never'}
                                    </small>
                                </div>
                                <div class="mt-2">
                                    <button class="btn btn-sm btn-outline-primary" 
                                            onclick="dashboard.trigger_sync('${entity.entity}')">
                                        <i class="fa fa-sync"></i> Sync Now
                                    </button>
                                </div>
                            </div>
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
                    <div class="row">
                        <div class="col-md-6">
                            <h5 class="mb-0"><i class="fa fa-list"></i> Sync Logs</h5>
                        </div>
                        <div class="col-md-6">
                            <div class="row">
                                <div class="col-md-4">
                                    <select class="form-control form-control-sm" id="status-filter">
                                        <option value="">All Statuses</option>
                                        <option value="Success">Success</option>
                                        <option value="Error">Error</option>
                                        <option value="Warning">Warning</option>
                                        <option value="Info">Info</option>
                                    </select>
                                </div>
                                <div class="col-md-4">
                                    <select class="form-control form-control-sm" id="entity-filter">
                                        <option value="">All Entities</option>
                                        <option value="Sales Invoice">Sales Invoice</option>
                                        <option value="Purchase Invoice">Purchase Invoice</option>
                                        <option value="Payment Entry">Payment Entry</option>
                                        <option value="Customer">Customer</option>
                                        <option value="Supplier">Supplier</option>
                                    </select>
                                </div>
                                <div class="col-md-4">
                                    <button class="btn btn-sm btn-primary" onclick="dashboard.apply_log_filters()">
                                        <i class="fa fa-filter"></i> Filter
                                    </button>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
                <div class="card-body">
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
                <table class="table table-striped">
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
                                <td>
                                    ${log.status === 'Error' ? 
                                        `<button class="btn btn-xs btn-outline-warning retry-btn" 
                                                data-log-name="${log.name}" onclick="dashboard.retry_job('${log.name}')">
                                            <i class="fa fa-redo"></i> Retry
                                        </button>` : 
                                        ''
                                    }
                                    <button class="btn btn-xs btn-outline-info" onclick="dashboard.view_log_details('${log.name}')">
                                        <i class="fa fa-eye"></i> Details
                                    </button>
                                </td>
                            </tr>
                        `).join('')}
                    </tbody>
                </table>
            </div>
            
            ${data.has_more ? 
                `<div class="text-center mt-3">
                    <button class="btn btn-outline-primary" onclick="dashboard.load_more_logs()">
                        Load More
                    </button>
                </div>` : 
                ''
            }
        `;

        $(this.wrapper).find('#logs-table').html(table_html);
    }

    load_configuration() {
        this.show_loading();
        frappe.call({
            method: 'xero.xero.page.xero_sync_dashboard.xero_sync_dashboard.get_sync_configuration',
            callback: (r) => {
                this.hide_loading();
                if (r.message) {
                    this.render_configuration(r.message);
                }
            }
        });
    }

    render_configuration(config) {
        const config_html = `
            <div class="row">
                <!-- Connection Settings -->
                <div class="col-md-6 mb-4">
                    <div class="card">
                        <div class="card-header">
                            <h5 class="mb-0"><i class="fa fa-plug"></i> Connection Settings</h5>
                        </div>
                        <div class="card-body">
                            <div class="form-group">
                                <label>Status:</label>
                                <span class="badge badge-${config.connection.connected ? 'success' : 'danger'} ml-2">
                                    ${config.connection.connected ? 'Connected' : 'Disconnected'}
                                </span>
                            </div>
                            <div class="form-group">
                                <label>
                                Tenant Name:</label>
                                <span class="text-muted">${config.connection.tenant_name || 'Not connected'}</span>
                            </div>
                            <div class="form-group">
                                <label>Client ID:</label>
                                <span class="text-muted">${config.connection.client_id ? '••••••••' : 'Not configured'}</span>
                            </div>
                            <div class="form-group">
                                <label>Last Token Refresh:</label>
                                <span class="text-muted">
                                    ${config.connection.last_token_refresh ? 
                                        frappe.datetime.comment_when(config.connection.last_token_refresh) : 
                                        'Never'
                                    }
                                </span>
                            </div>
                            <div class="mt-3">
                                <button class="btn btn-primary btn-sm" onclick="dashboard.test_connection()">
                                    <i class="fa fa-plug"></i> Test Connection
                                </button>
                                <button class="btn btn-outline-secondary btn-sm ml-2" onclick="dashboard.refresh_token()">
                                    <i class="fa fa-refresh"></i> Refresh Token
                                </button>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Sync Settings -->
                <div class="col-md-6 mb-4">
                    <div class="card">
                        <div class="card-header">
                            <h5 class="mb-0"><i class="fa fa-cog"></i> Sync Settings</h5>
                        </div>
                        <div class="card-body">
                            <div class="form-group">
                                <div class="form-check">
                                    <input class="form-check-input" type="checkbox" id="auto-sync" 
                                           ${config.sync_settings.auto_sync_enabled ? 'checked' : ''}>
                                    <label class="form-check-label" for="auto-sync">
                                        Enable Auto Sync
                                    </label>
                                </div>
                            </div>
                            <div class="form-group">
                                <label>Sync Frequency:</label>
                                <select class="form-control form-control-sm" id="sync-frequency">
                                    <option value="Hourly" ${config.sync_settings.sync_frequency === 'Hourly' ? 'selected' : ''}>Hourly</option>
                                    <option value="Daily" ${config.sync_settings.sync_frequency === 'Daily' ? 'selected' : ''}>Daily</option>
                                    <option value="Weekly" ${config.sync_settings.sync_frequency === 'Weekly' ? 'selected' : ''}>Weekly</option>
                                </select>
                            </div>
                            <div class="form-group">
                                <label>Batch Size:</label>
                                <input type="number" class="form-control form-control-sm" 
                                       id="batch-size" value="${config.sync_settings.batch_size || 50}">
                            </div>
                            <div class="form-group">
                                <label>Retry Attempts:</label>
                                <input type="number" class="form-control form-control-sm" 
                                       id="retry-attempts" value="${config.sync_settings.max_retries || 3}">
                            </div>
                            <div class="mt-3">
                                <button class="btn btn-success btn-sm" onclick="dashboard.save_sync_settings()">
                                    <i class="fa fa-save"></i> Save Settings
                                </button>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Entity Mappings -->
                <div class="col-md-12">
                    <div class="card">
                        <div class="card-header">
                            <h5 class="mb-0"><i class="fa fa-exchange-alt"></i> Entity Mappings</h5>
                        </div>
                        <div class="card-body">
                            <div class="row">
                                <div class="col-md-6">
                                    <h6>Account Mappings</h6>
                                    <p class="text-muted">
                                        Total: ${config.mappings.accounts || 0} mappings configured
                                    </p>
                                    <button class="btn btn-outline-primary btn-sm" onclick="frappe.set_route('Form', 'Xero Settings')">
                                        <i class="fa fa-edit"></i> Manage Account Mappings
                                    </button>
                                </div>
                                <div class="col-md-6">
                                    <h6>Tax Mappings</h6>
                                    <p class="text-muted">
                                        Total: ${config.mappings.taxes || 0} mappings configured
                                    </p>
                                    <button class="btn btn-outline-primary btn-sm" onclick="frappe.set_route('Form', 'Xero Settings')">
                                        <i class="fa fa-edit"></i> Manage Tax Mappings
                                    </button>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        `;

        $(this.wrapper).find('#config').html(config_html);
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
                frappe.call({
                    method: 'xero.xero.page.xero_sync_dashboard.xero_sync_dashboard.trigger_manual_sync',
                    args: { entity_type: entity },
                    callback: (r) => {
                        if (r.message && r.message.success) {
                            frappe.show_alert({
                                message: `${entity} sync initiated successfully`,
                                indicator: 'green'
                            });
                            this.refresh_current_tab();
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
        
        this.logs_filters = {
            status: status,
            erpnext_doc_type: entity
        };
        this.logs_start = 0;
        this.load_logs_data(0, this.logs_filters);
    }

    load_more_logs() {
        this.logs_start += 20;
        this.load_logs_data(this.logs_start, this.logs_filters);
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

    // Health Monitoring Tab
    load_health_monitoring() {
        this.show_loading();
        frappe.call({
            method: 'xero.xero.page.xero_sync_dashboard.xero_sync_dashboard.get_health_monitoring_metrics',
            callback: (r) => {
                this.hide_loading();
                if (r.message && !r.message.error) {
                    this.render_health_monitoring(r.message);
                } else {
                    this.show_error('Failed to load health monitoring metrics', r.message?.error);
                }
            }
        });
    }

    render_health_monitoring(data) {
        const health_html = `
            <div class="row">
                <!-- System Uptime -->
                <div class="col-md-12 mb-4">
                    <div class="card">
                        <div class="card-header">
                            <h5 class="mb-0"><i class="fa fa-heartbeat"></i> System Health (Last 24h)</h5>
                        </div>
                        <div class="card-body">
                            <div class="row text-center">
                                <div class="col-md-3">
                                    <h3 class="text-${data.uptime_percentage >= 95 ? 'success' : 'danger'}">${data.uptime_percentage}%</h3>
                                    <p class="text-muted">Uptime</p>
                                </div>
                                <div class="col-md-3">
                                    <h3 class="text-success">${data.successful_operations_24h || 0}</h3>
                                    <p class="text-muted">Successful Operations</p>
                                </div>
                                <div class="col-md-3">
                                    <h3 class="text-info">${data.total_operations_24h || 0}</h3>
                                    <p class="text-muted">Total Operations</p>
                                </div>
                                <div class="col-md-3">
                                    <h3 class="text-${data.stuck_jobs.length > 0 ? 'danger' : 'success'}">${data.stuck_jobs.length}</h3>
                                    <p class="text-muted">Stuck Jobs</p>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- API Performance -->
                <div class="col-md-6 mb-4">
                    <div class="card">
                        <div class="card-header">
                            <h5 class="mb-0"><i class="fa fa-tachometer-alt"></i> API Performance</h5>
                        </div>
                        <div class="card-body">
                            ${data.api_performance && Object.keys(data.api_performance).length > 0 ? `
                                <table class="table table-sm">
                                    <tr>
                                        <td><strong>Avg Response Time:</strong></td>
                                        <td>${(data.api_performance.avg_time || 0).toFixed(2)}s</td>
                                    </tr>
                                    <tr>
                                        <td><strong>Max Response Time:</strong></td>
                                        <td>${(data.api_performance.max_time || 0).toFixed(2)}s</td>
                                    </tr>
                                    <tr>
                                        <td><strong>Min Response Time:</strong></td>
                                        <td>${(data.api_performance.min_time || 0).toFixed(2)}s</td>
                                    </tr>
                                    <tr>
                                        <td><strong>Total API Calls:</strong></td>
                                        <td>${data.api_performance.total_calls || 0}</td>
                                    </tr>
                                    <tr>
                                        <td><strong>Slow Calls (>5s):</strong></td>
                                        <td class="text-warning">${data.api_performance.slow_calls || 0}</td>
                                    </tr>
                                </table>
                            ` : '<p class="text-muted">No API performance data available</p>'}
                        </div>
                    </div>
                </div>

                <!-- Token Refresh Metrics -->
                <div class="col-md-6 mb-4">
                    <div class="card">
                        <div class="card-header">
                            <h5 class="mb-0"><i class="fa fa-key"></i> Token Refresh Status</h5>
                        </div>
                        <div class="card-body">
                            ${data.token_metrics && Object.keys(data.token_metrics).length > 0 ? `
                                <table class="table table-sm">
                                    <tr>
                                        <td><strong>Total Refreshes:</strong></td>
                                        <td>${data.token_metrics.total_refreshes || 0}</td>
                                    </tr>
                                    <tr>
                                        <td><strong>Successful:</strong></td>
                                        <td class="text-success">${data.token_metrics.successful || 0}</td>
                                    </tr>
                                    <tr>
                                        <td><strong>Failed:</strong></td>
                                        <td class="text-danger">${data.token_metrics.failed || 0}</td>
                                    </tr>
                                    <tr>
                                        <td><strong>Last Refresh:</strong></td>
                                        <td>${data.token_metrics.last_refresh ? frappe.datetime.comment_when(data.token_metrics.last_refresh) : 'Never'}</td>
                                    </tr>
                                    <tr>
                                        <td><strong>Success Rate:</strong></td>
                                        <td>
                                            ${data.token_metrics.total_refreshes > 0 ? 
                                                Math.round((data.token_metrics.successful / data.token_metrics.total_refreshes) * 100) : 0}%
                                        </td>
                                    </tr>
                                </table>
                            ` : '<p class="text-muted">No token refresh data available</p>'}
                        </div>
                    </div>
                </div>

                <!-- Error by Category -->
                <div class="col-md-12 mb-4">
                    <div class="card">
                        <div class="card-header">
                            <h5 class="mb-0"><i class="fa fa-exclamation-triangle"></i> Errors by Category (Last 7 Days)</h5>
                        </div>
                        <div class="card-body">
                            ${data.error_by_category && data.error_by_category.length > 0 ? `
                                <div class="table-responsive">
                                    <table class="table table-sm">
                                        <thead>
                                            <tr>
                                                <th>Category</th>
                                                <th>Count</th>
                                                <th>Percentage</th>
                                                <th>Distribution</th>
                                            </tr>
                                        </thead>
                                        <tbody>
                                            ${data.error_by_category.map(cat => `
                                                <tr>
                                                    <td>${cat.category}</td>
                                                    <td><span class="badge badge-danger">${cat.count}</span></td>
                                                    <td>${(cat.percentage || 0).toFixed(1)}%</td>
                                                    <td>
                                                        <div class="progress" style="height: 20px;">
                                                            <div class="progress-bar bg-danger" style="width: ${cat.percentage}%">
                                                                ${Math.round(cat.percentage)}%
                                                            </div>
                                                        </div>
                                                    </td>
                                                </tr>
                                            `).join('')}
                                        </tbody>
                                    </table>
                                </div>
                            ` : '<p class="text-muted">No errors in the last 7 days 🎉</p>'}
                        </div>
                    </div>
                </div>

                <!-- Stuck Jobs -->
                ${data.stuck_jobs && data.stuck_jobs.length > 0 ? `
                    <div class="col-md-12 mb-4">
                        <div class="card border-danger">
                            <div class="card-header bg-danger text-white">
                                <h5 class="mb-0"><i class="fa fa-exclamation-circle"></i> Stuck Jobs (Running > 1 Hour)</h5>
                            </div>
                            <div class="card-body">
                                ${data.stuck_jobs.map(job => `
                                    <div class="alert alert-danger mb-2">
                                        <div class="d-flex justify-content-between">
                                            <strong>${job.job_name}</strong>
                                            <span class="badge badge-danger">${job.duration_minutes} minutes</span>
                                        </div>
                                        <small class="text-muted">
                                            Started: ${frappe.datetime.comment_when(job.started_at || job.creation)}
                                        </small>
                                    </div>
                                `).join('')}
                            </div>
                        </div>
                    </div>
                ` : ''}

                <!-- Rate Limit Hits -->
                ${data.rate_limit_hits && data.rate_limit_hits.length > 0 ? `
                    <div class="col-md-12 mb-4">
                        <div class="card">
                            <div class="card-header">
                                <h5 class="mb-0"><i class="fa fa-ban"></i> Rate Limit Hits (Last 7 Days)</h5>
                            </div>
                            <div class="card-body">
                                <div class="table-responsive">
                                    <table class="table table-sm">
                                        <thead>
                                            <tr>
                                                <th>Hour</th>
                                                <th>Hits</th>
                                            </tr>
                                        </thead>
                                        <tbody>
                                            ${data.rate_limit_hits.slice(0, 10).map(hit => `
                                                <tr>
                                                    <td>${frappe.datetime.str_to_user(hit.hour)}</td>
                                                    <td><span class="badge badge-warning">${hit.hits}</span></td>
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

        $(this.wrapper).find('#health').html(health_html);
    }

    // Data Integrity Tab
    load_data_integrity() {
        this.show_loading();
        frappe.call({
            method: 'xero.xero.page.xero_sync_dashboard.xero_sync_dashboard.get_data_integrity_metrics',
            callback: (r) => {
                this.hide_loading();
                if (r.message && !r.message.error) {
                    this.render_data_integrity(r.message);
                } else {
                    this.show_error('Failed to load data integrity metrics', r.message?.error);
                }
            }
        });
    }

    render_data_integrity(data) {
        const integrity_html = `
            <div class="row">
                <!-- Summary Cards -->
                <div class="col-md-12 mb-4">
                    <div class="row">
                        <div class="col-md-3">
                            <div class="card ${data.total_orphaned > 0 ? 'border-warning' : ''}">
                                <div class="card-body text-center">
                                    <h3 class="text-warning">${data.total_orphaned || 0}</h3>
                                    <p class="text-muted">Orphaned Records</p>
                                    <small>Have Xero ID but no sync status</small>
                                </div>
                            </div>
                        </div>
                        <div class="col-md-3">
                            <div class="card ${data.total_missing_ids > 0 ? 'border-danger' : ''}">
                                <div class="card-body text-center">
                                    <h3 class="text-danger">${data.total_missing_ids || 0}</h3>
                                    <p class="text-muted">Missing Xero IDs</p>
                                    <small>Marked synced but no ID</small>
                                </div>
                            </div>
                        </div>
                        <div class="col-md-3">
                            <div class="card ${data.total_pending > 0 ? 'border-info' : ''}">
                                <div class="card-body text-center">
                                    <h3 class="text-info">${data.total_pending || 0}</h3>
                                    <p class="text-muted">Pending Prerequisites</p>
                                    <small>Waiting for dependencies</small>
                                </div>
                            </div>
                        </div>
                        <div class="col-md-3">
                            <div class="card ${data.total_errors > 0 ? 'border-danger' : ''}">
                                <div class="card-body text-center">
                                    <h3 class="text-danger">${data.total_errors || 0}</h3>
                                    <p class="text-muted">Documents with Errors</p>
                                    <small>Require manual intervention</small>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Orphaned Records Detail -->
                ${data.orphaned_invoices && data.orphaned_invoices.length > 0 ? `
                    <div class="col-md-6 mb-4">
                        <div class="card border-warning">
                            <div class="card-header">
                                <h5 class="mb-0"><i class="fa fa-unlink"></i> Orphaned Records</h5>
                            </div>
                            <div class="card-body">
                                <div class="table-responsive">
                                    <table class="table table-sm">
                                        <thead>
                                            <tr>
                                                <th>DocType</th>
                                                <th>Count</th>
                                            </tr>
                                        </thead>
                                        <tbody>
                                            ${data.orphaned_invoices.map(o => `
                                                <tr>
                                                    <td>${o.doctype}</td>
                                                    <td><span class="badge badge-warning">${o.count}</span></td>
                                                </tr>
                                            `).join('')}
                                        </tbody>
                                    </table>
                                </div>
                            </div>
                        </div>
                    </div>
                ` : ''}

                <!-- Missing IDs Detail -->
                ${data.missing_ids && data.missing_ids.length > 0 ? `
                    <div class="col-md-6 mb-4">
                        <div class="card border-danger">
                            <div class="card-header">
                                <h5 class="mb-0"><i class="fa fa-exclamation-triangle"></i> Missing Xero IDs</h5>
                            </div>
                            <div class="card-body">
                                <div class="table-responsive">
                                    <table class="table table-sm">
                                        <thead>
                                            <tr>
                                                <th>DocType</th>
                                                <th>Count</th>
                                            </tr>
                                        </thead>
                                        <tbody>
                                            ${data.missing_ids.map(m => `
                                                <tr>
                                                    <td>${m.doctype}</td>
                                                    <td><span class="badge badge-danger">${m.count}</span></td>
                                                </tr>
                                            `).join('')}
                                        </tbody>
                                    </table>
                                </div>
                            </div>
                        </div>
                    </div>
                ` : ''}

                <!-- Recent Validation Errors -->
                ${data.validation_errors && data.validation_errors.length > 0 ? `
                    <div class="col-md-12 mb-4">
                        <div class="card">
                            <div class="card-header">
                                <h5 class="mb-0"><i class="fa fa-times-circle"></i> Recent Validation Errors</h5>
                            </div>
                            <div class="card-body">
                                ${data.validation_errors.slice(0, 10).map(err => `
                                    <div class="alert alert-warning mb-2">
                                        <div class="d-flex justify-content-between">
                                            <strong>${err.erpnext_doc_type} ${err.erpnext_doc_name}</strong>
                                            <small class="text-muted">${frappe.datetime.comment_when(err.timestamp)}</small>
                                        </div>
                                        <p class="mb-0 small">${err.message}</p>
                                    </div>
                                `).join('')}
                            </div>
                        </div>
                    </div>
                ` : ''}

                <!-- Mapping Errors -->
                ${data.mapping_errors && data.mapping_errors.length > 0 ? `
                    <div class="col-md-12 mb-4">
                        <div class="card">
                            <div class="card-header">
                                <h5 class="mb-0"><i class="fa fa-exchange-alt"></i> Mapping Errors (Last 7 Days)</h5>
                            </div>
                            <div class="card-body">
                                <div class="table-responsive">
                                    <table class="table table-sm">
                                        <thead>
                                            <tr>
                                                <th>Error Message</th>
                                                <th>Occurrences</th>
                                            </tr>
                                        </thead>
                                        <tbody>
                                            ${data.mapping_errors.map(err => `
                                                <tr>
                                                    <td>${err.message}</td>
                                                    <td><span class="badge badge-danger">${err.count}</span></td>
                                                </tr>
                                            `).join('')}
                                        </tbody>
                                    </table>
                                </div>
                            </div>
                        </div>
                    </div>
                ` : ''}

                ${(data.total_orphaned + data.total_missing_ids + data.total_pending + data.total_errors) === 0 ? `
                    <div class="col-md-12">
                        <div class="alert alert-success text-center">
                            <h4><i class="fa fa-check-circle"></i> All Systems Green!</h4>
                            <p class="mb-0">No data integrity issues detected.</p>
                        </div>
                    </div>
                ` : ''}
            </div>
        `;

        $(this.wrapper).find('#integrity').html(integrity_html);
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
            <div class="row">
                <!-- Summary Card -->
                <div class="col-md-12 mb-4">
                    <div class="card">
                        <div class="card-header bg-primary text-white">
                            <h5 class="mb-0"><i class="fa fa-history"></i> Last Sync Attempt Overview</h5>
                        </div>
                        <div class="card-body">
                            <div class="row text-center">
                                <div class="col-md-3">
                                    <h4 class="text-primary">${data.total_attempts || 0}</h4>
                                    <p class="text-muted">Total Sync Attempts</p>
                                </div>
                                <div class="col-md-3">
                                    <h4 class="text-success">${data.successful_attempts || 0}</h4>
                                    <p class="text-muted">Successful</p>
                                </div>
                                <div class="col-md-3">
                                    <h4 class="text-danger">${data.failed_attempts || 0}</h4>
                                    <p class="text-muted">Failed</p>
                                </div>
                                <div class="col-md-3">
                                    <h4 class="text-warning">${data.in_progress_attempts || 0}</h4>
                                    <p class="text-muted">In Progress</p>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Sync Attempts List -->
                <div class="col-md-12">
                    <div class="card">
                        <div class="card-header">
                            <h5 class="mb-0"><i class="fa fa-list"></i> Recent Sync Attempts</h5>
                        </div>
                        <div class="card-body">
                            ${data.sync_attempts && data.sync_attempts.length > 0 ?
                                data.sync_attempts.map(attempt => `
                                    <div class="card mb-3 border-${this.get_sync_attempt_color(attempt.overall_status)}">
                                        <div class="card-header bg-${this.get_sync_attempt_color(attempt.overall_status)} text-white">
                                            <div class="row align-items-center">
                                                <div class="col-md-6">
                                                    <h6 class="mb-0">
                                                        <i class="fa fa-${this.get_sync_direction_icon(attempt.sync_direction)}"></i>
                                                        ${attempt.sync_direction}
                                                    </h6>
                                                </div>
                                                <div class="col-md-3">
                                                    <small>${frappe.datetime.str_to_user(attempt.sync_time)}</small>
                                                </div>
                                                <div class="col-md-3 text-right">
                                                    <span class="badge badge-light text-${this.get_sync_attempt_color(attempt.overall_status)}">
                                                        ${attempt.overall_status}
                                                    </span>
                                                </div>
                                            </div>
                                        </div>
                                        <div class="card-body">
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
                                                            <span class="badge badge-warning ml-2">${attempt.in_progress_count || 0} In Progress</span>
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
                                '<div class="alert alert-info">No sync attempts found in the last 7 days.</div>'
                            }
                        </div>
                    </div>
                </div>
            </div>
        `;

        $(this.wrapper).find('#last-sync').html(last_sync_html);
    }

    get_sync_attempt_color(status) {
        const colors = {
            'Success': 'success',
            'Failed': 'danger',
            'In Progress': 'warning',
            'Partial Success': 'warning'
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
            case 'analytics':
                this.load_analytics();
                break;
            case 'entities':
                this.load_entity_status();
                break;
            case 'logs':
                this.load_logs_data(this.logs_start, this.logs_filters);
                break;
            case 'health':
                this.load_health_monitoring();
                break;
            case 'integrity':
                this.load_data_integrity();
                break;
            case 'last-sync':
                this.load_last_sync_attempts();
                break;
            case 'performance':
                this.load_performance_metrics();
                break;
            case 'config':
                this.load_configuration();
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
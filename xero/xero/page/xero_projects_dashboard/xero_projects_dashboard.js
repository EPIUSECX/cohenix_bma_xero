frappe.pages['xero-projects-dashboard'].on_page_load = function(wrapper) {
    var page = frappe.ui.make_app_page({
        parent: wrapper,
        title: 'Xero Projects Dashboard',
        single_column: true
    });

    // Add refresh button
    page.set_primary_action('Refresh', () => {
        refresh_dashboard(page);
    });

    // Add sync button
    page.set_secondary_action('Sync Projects', () => {
        frappe.call({
            method: 'xero.api.xero_projects.enqueue_sync_projects',
            callback: function() {
                frappe.show_alert({
                    message: __('Project sync initiated'),
                    indicator: 'green'
                });
                setTimeout(() => refresh_dashboard(page), 3000);
            }
        });
    });

    setup_dashboard(page);
};

function setup_dashboard(page) {
    page.main.html(`
        <div class="xero-project-dashboard">
            <div class="row">
                <div class="col-md-12">
                    <div class="widget project-summary"></div>
                </div>
            </div>
            <div class="row">
                <div class="col-md-6">
                    <div class="widget recent-projects"></div>
                </div>
                <div class="col-md-6">
                    <div class="widget profitability"></div>
                </div>
            </div>
        </div>
    `);

    refresh_dashboard(page);
}

function refresh_dashboard(page) {
    frappe.call({
        method: 'xero.xero.page.xero_projects_dashboard.xero_projects_dashboard.get_dashboard_data',
        callback: function(r) {
            if (r.message) {
                render_summary(page, r.message.summary);
                render_recent_projects(page, r.message.recent_projects);
                render_profitability(page, r.message.profitability);
            }
        }
    });
}

function render_summary(page, data) {
    const summary_html = `
        <div class="project-summary-section">
            <h6 class="text-muted">Project Summary</h6>
            <div class="row">
                ${data.map(status => `
                    <div class="col-md-4">
                        <div class="card">
                            <div class="card-body">
                                <h6>${status.status}</h6>
                                <div class="row">
                                    <div class="col-6">
                                        <p class="text-muted mb-1">Projects</p>
                                        <h3 class="mb-0">${status.count}</h3>
                                    </div>
                                    <div class="col-6">
                                        <p class="text-muted mb-1">Est. Value</p>
                                        <h3 class="mb-0">${format_currency(status.total_estimate)}</h3>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                `).join('')}
            </div>
        </div>
    `;
    
    page.main.find('.project-summary').html(summary_html);
}

function render_recent_projects(page, projects) {
    const projects_html = `
        <div class="recent-projects-section">
            <h6 class="text-muted">Recent Projects</h6>
            <div class="table-responsive">
                <table class="table table-bordered">
                    <thead>
                        <tr>
                            <th>Project</th>
                            <th>Status</th>
                            <th>Deadline</th>
                            <th>Est. Amount</th>
                            <th>Cost</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${projects.map(project => `
                            <tr>
                                <td>
                                    <a href="/app/xero-project/${project.name}">${project.name}</a>
                                </td>
                                <td>${project.status}</td>
                                <td>${frappe.datetime.str_to_user(project.deadline)}</td>
                                <td>${format_currency(project.estimate_amount)}</td>
                                <td>${format_currency(project.total_cost)}</td>
                            </tr>
                        `).join('')}
                    </tbody>
                </table>
            </div>
        </div>
    `;
    
    page.main.find('.recent-projects').html(projects_html);
}

function render_profitability(page, data) {
    const profit_html = `
        <div class="profitability-section">
            <h6 class="text-muted">Project Profitability</h6>
            <div class="table-responsive">
                <table class="table table-bordered">
                    <thead>
                        <tr>
                            <th>Project</th>
                            <th>Margin</th>
                            <th>Margin %</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${data.map(project => `
                            <tr>
                                <td>
                                    <a href="/app/xero-project/${project.name}">${project.name}</a>
                                </td>
                                <td>${format_currency(project.margin)}</td>
                                <td>${format_number(project.margin_percent, 1)}%</td>
                            </tr>
                        `).join('')}
                    </tbody>
                </table>
            </div>
        </div>
    `;
    
    page.main.find('.profitability').html(profit_html);
}

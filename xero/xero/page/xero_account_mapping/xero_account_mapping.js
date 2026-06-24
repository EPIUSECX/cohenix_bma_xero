frappe.pages['xero-account-mapping'].on_page_load = function (wrapper) {
    const page = frappe.ui.make_app_page({
        parent: wrapper,
        title: __('Xero Mapping'),
        single_column: true,
    });
    const app = new XeroMapping(page);
    app.init();
    window.xero_mapping = app;
    // Paint the whole page area with the canvas colour (kills the white gap).
    $(wrapper).addClass('xero-mapping-page');
};

function _esc(s) {
    if (s === null || s === undefined) return '';
    return String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

class XeroMapping {
    constructor(page) { this.page = page; this.wrapper = page.main; this.ws = null; }

    init() {
        this.page.set_primary_action(__('Apply'), () => this.apply(), 'check');
        this.page.add_action_item(__('Re-check'), () => this.load());
        this.page.add_action_item(__('Open mapping tables'), () => frappe.set_route('Form', 'Xero Settings'));
        this.page.add_action_item(__('Sync Dashboard'), () => frappe.set_route('xero-sync-dashboard'));
        this.body = $('<div class="xmap"><div class="xmap-content"></div></div>').appendTo(this.wrapper);
        this.content = this.body.find('.xmap-content');
        this.load();
    }

    load() {
        this.content.html('<div class="xmap-empty"><span class="text-muted">Refreshing the live Xero chart of accounts &amp; tax rates…</span></div>');
        frappe.call({
            method: 'xero.utils.account_mapper.get_mapping_workspace',
            freeze: false,
            callback: (r) => {
                if (!r.message) { this.content.html('<div class="xmap-empty">No response from server.</div>'); return; }
                this.ws = r.message;
                this.render();
            },
            error: () => this.content.html('<div class="xmap-empty">Failed to load. Is Xero connected?</div>'),
        });
    }

    // ---- option builders ----
    xeroAcctOptions(selCode) {
        let o = '<option value="">— select Xero account —</option>';
        (this.ws.xero_accounts || []).forEach(x => {
            const sel = selCode && selCode === x.code ? 'selected' : '';
            o += `<option value="${_esc(x.code)}" data-name="${_esc(x.name)}" data-id="${_esc(x.account_id)}" ${sel}>${_esc(x.code)} — ${_esc(x.name)}</option>`;
        });
        return o;
    }
    erpAcctOptions() {
        let o = '<option value="">— select ERPNext account —</option>';
        (this.ws.erpnext_accounts || []).forEach(a => { o += `<option value="${_esc(a.name)}">${_esc(a.label)}</option>`; });
        return o;
    }
    xeroTaxOptions(selCode) {
        let o = '<option value="">— select Xero tax rate —</option>';
        (this.ws.xero_tax_rates || []).forEach(t => {
            const sel = selCode && selCode === t.tax_type ? 'selected' : '';
            o += `<option value="${_esc(t.tax_type)}" data-name="${_esc(t.name)}" data-rate="${_esc(t.rate)}" ${sel}>${_esc(t.name)} (${_esc(t.rate)}%)</option>`;
        });
        return o;
    }

    render() {
        const ws = this.ws, s = ws.summary || {}, dirs = ws.directions || {};
        const need = (s.need_to_xero || 0) + (s.need_from_xero || 0) + (s.need_tax || 0);
        const totalMapped = (s.mapped_accounts || 0);
        const pct = (totalMapped + need) ? Math.round(totalMapped / (totalMapped + need) * 100) : 100;

        let html = `
            <div class="xmap-summary">
                <span class="xmap-stat"><b>${totalMapped}</b>accounts mapped</span>
                <span class="xmap-stat"><b>${s.mapped_tax || 0}</b>tax templates mapped</span>
                <span class="xmap-stat attn"><b>${need}</b>need attention</span>
                <span class="xmap-progress" title="${pct}% mapped"><span style="width:${pct}%;"></span></span>
            </div>`;

        if (dirs.to_xero) html += this.sectionAccounts('to', 'ERPNext → Xero', 'ERPNext accounts not yet in Xero', ws.accounts_to_xero || []);
        if (dirs.from_xero) html += this.sectionFromXero(ws.accounts_from_xero || []);
        html += this.sectionTax(ws.tax || []);

        this.content.html(html);
        this.bind();
    }

    // ERPNext → Xero
    sectionAccounts(sec, title, subtitle, rows) {
        if (!rows.length) return this.doneCard(title, subtitle);

        const exact = rows.filter(r => r.status === 'exact');
        const review = rows.filter(r => r.status !== 'exact');

        let exactBanner = '';
        if (exact.length) {
            exactBanner = `<div class="xmap-exact"><span class="ic">✓</span>
                <span><b>${exact.length}</b> exact match${exact.length > 1 ? 'es' : ''} will be linked automatically (no duplicates created).</span>
                <a data-toggle-exact="${sec}">Review</a></div>`;
        }

        const reviewRows = review.map((u, i) => this.accountRow(sec, u, rows.indexOf(u))).join('');
        const exactRows = exact.map((u) => this.accountRow(sec, u, rows.indexOf(u))).join('');

        return `
            <div class="xmap-card" data-sec="${sec}">
                <div class="xmap-card-head">
                    <div><div class="xmap-card-title">${title}</div><div class="xmap-card-sub">${subtitle} — “Create” writes to Xero</div></div>
                    <div class="xmap-tools">
                        <input class="xmap-search" data-sec="${sec}" placeholder="Search accounts…">
                        <button class="xmap-bulk" data-bulk="suggested" data-sec="${sec}">Accept suggestions</button>
                        <button class="xmap-bulk" data-bulk="skip" data-sec="${sec}">Skip all</button>
                        <span class="xmap-count">${review.length} to review</span>
                    </div>
                </div>
                ${exactBanner}
                <div class="xmap-exact-rows" data-sec="${sec}" style="display:none;">
                    <div class="xmap-body-scroll"><table class="xmap-table"><tbody>${exactRows}</tbody></table></div>
                </div>
                <div class="xmap-body-scroll">
                    <table class="xmap-table">
                        <thead><tr><th>Account</th><th class="xmap-col-status">Status</th><th class="xmap-col-action">Action</th><th>Target</th></tr></thead>
                        <tbody>${reviewRows || '<tr><td colspan="4" class="xmap-empty">All matched automatically — nothing to review.</td></tr>'}</tbody>
                    </table>
                </div>
            </div>`;
    }

    accountRow(sec, u, idx) {
        const pill = { exact: 'pill-exact', fuzzy: 'pill-review', create: 'pill-create', tax: 'pill-tax' }[u.status] || 'pill-muted';
        const pillText = { exact: 'Exact match', fuzzy: 'Needs review', create: 'Will create', tax: 'Tax' }[u.status] || u.status;
        // default action per status: exact→map(link), fuzzy→map(review), create→create, tax→skip
        const def = (u.status === 'exact' || u.status === 'fuzzy') ? 'map' : (u.status === 'tax' ? 'skip' : 'create');
        const selCode = (u.exact && u.exact.code) || (u.suggested && u.suggested.code) || '';
        const sugLabel = u.exact ? `Exact: ${_esc(u.exact.code)} — ${_esc(u.exact.name)}`
            : (u.suggested ? `Suggested (${_esc(u.suggested.confidence)})` : 'No existing match — will create');
        let badges = '';
        if (u.has_recent_error) badges += '<span class="xmap-pill pill-fail" style="margin-right:4px;">Failing now</span>';
        badges += `<span class="xmap-pill pill-muted">${_esc(u.root_type)}</span>`;
        return `
            <tr data-name="${_esc((u.account_name || '').toLowerCase())}">
                <td class="xmap-acct"><b>${_esc(u.account_name)}</b><div class="meta">${_esc(u.erpnext_account)}</div><div style="margin-top:5px;">${badges}</div></td>
                <td><span class="xmap-pill ${pill}">${pillText}</span></td>
                <td><select class="xmap-action" data-sec="${sec}" data-idx="${idx}">
                    <option value="map" ${def === 'map' ? 'selected' : ''}>${u.exact ? 'Link to Xero' : 'Map to existing'}</option>
                    <option value="create" ${def === 'create' ? 'selected' : ''}>Create in Xero</option>
                    <option value="skip" ${def === 'skip' ? 'selected' : ''}>Skip</option>
                </select></td>
                <td><select class="xmap-target" data-sec="${sec}" data-idx="${idx}" ${def === 'map' ? '' : 'disabled'}>${this.xeroAcctOptions(selCode)}</select>
                    <div class="xmap-hint ${(u.exact || u.suggested) ? 'sug' : ''}">${sugLabel}</div></td>
            </tr>`;
    }

    // Xero → ERPNext
    sectionFromXero(rows) {
        if (!rows.length) return this.doneCard('From Xero → ERPNext', 'Xero accounts not yet in ERPNext');
        const body = rows.map((u, idx) => {
            const sug = u.suggested_erpnext;
            const def = sug ? 'map' : 'create';
            return `
                <tr data-name="${_esc((u.xero_name || '').toLowerCase())}">
                    <td class="xmap-acct"><b>${_esc(u.xero_name)}</b><div class="meta">${_esc(u.xero_code)} · ${_esc(u.xero_type)}</div></td>
                    <td><span class="xmap-pill ${sug ? 'pill-review' : 'pill-create'}">${sug ? 'Needs review' : 'Will create'}</span></td>
                    <td><select class="xmap-action" data-sec="from" data-idx="${idx}">
                        <option value="map" ${def === 'map' ? 'selected' : ''}>Map to existing</option>
                        <option value="create" ${def === 'create' ? 'selected' : ''}>Create in ERPNext</option>
                        <option value="skip">Skip</option>
                    </select></td>
                    <td><select class="xmap-target" data-sec="from" data-idx="${idx}" ${def === 'map' ? '' : 'disabled'}>${this.erpAcctOptions()}</select>
                        <div class="xmap-hint ${sug ? 'sug' : ''}">${sug ? 'Suggested: ' + _esc(sug) + ' (' + _esc(u.confidence) + ')' : 'No match — will create in ERPNext'}</div></td>
                </tr>`;
        }).join('');
        return `
            <div class="xmap-card" data-sec="from">
                <div class="xmap-card-head">
                    <div><div class="xmap-card-title">From Xero → ERPNext</div><div class="xmap-card-sub">Xero accounts not yet in ERPNext</div></div>
                    <div class="xmap-tools"><input class="xmap-search" data-sec="from" placeholder="Search…"><span class="xmap-count">${rows.length} to review</span></div>
                </div>
                <div class="xmap-body-scroll"><table class="xmap-table">
                    <thead><tr><th>Xero account</th><th class="xmap-col-status">Status</th><th class="xmap-col-action">Action</th><th>Target</th></tr></thead>
                    <tbody>${body}</tbody></table></div>
            </div>`;
    }

    // Tax
    sectionTax(rows) {
        if (!rows.length) return this.doneCard('Tax rates', 'ERPNext item tax templates → Xero tax rates');
        const body = rows.map((u, idx) => {
            const sug = u.suggested;
            const def = sug ? 'map' : 'skip';
            return `
                <tr data-name="${_esc((u.erpnext_tax_template || '').toLowerCase())}">
                    <td class="xmap-acct"><b>${_esc(u.erpnext_tax_template)}</b><div class="meta">${_esc(u.erpnext_rate)}%</div></td>
                    <td><span class="xmap-pill ${sug ? 'pill-review' : 'pill-muted'}">${sug ? 'Needs review' : 'No match'}</span></td>
                    <td><select class="xmap-action" data-sec="tax" data-idx="${idx}">
                        <option value="map" ${def === 'map' ? 'selected' : ''}>Map to existing</option>
                        <option value="skip" ${def === 'skip' ? 'selected' : ''}>Skip</option>
                    </select></td>
                    <td><select class="xmap-target" data-sec="tax" data-idx="${idx}" ${def === 'map' ? '' : 'disabled'}>${this.xeroTaxOptions(sug && sug.tax_type)}</select>
                        <div class="xmap-hint ${sug ? 'sug' : ''}">${sug ? 'Suggested (' + _esc(sug.confidence) + ')' : 'No suggested match'}</div></td>
                </tr>`;
        }).join('');
        return `
            <div class="xmap-card" data-sec="tax">
                <div class="xmap-card-head">
                    <div><div class="xmap-card-title">Tax rates</div><div class="xmap-card-sub">ERPNext item tax templates → Xero tax rates</div></div>
                    <span class="xmap-count">${rows.length} to review</span>
                </div>
                <div class="xmap-body-scroll"><table class="xmap-table">
                    <thead><tr><th>Tax template</th><th class="xmap-col-status">Status</th><th class="xmap-col-action">Action</th><th>Target</th></tr></thead>
                    <tbody>${body}</tbody></table></div>
            </div>`;
    }

    doneCard(title, subtitle) {
        return `<div class="xmap-card xmap-done"><span class="ic">✓</span><b>${title}</b><span>${subtitle} — nothing needs attention</span></div>`;
    }

    bind() {
        const root = this.content;
        root.on('change', '.xmap-action', function () {
            const sec = $(this).data('sec'), idx = $(this).data('idx');
            root.find(`.xmap-target[data-sec="${sec}"][data-idx="${idx}"]`).prop('disabled', $(this).val() !== 'map');
        });
        root.on('click', '[data-toggle-exact]', function (e) {
            e.preventDefault();
            const sec = $(this).data('toggle-exact');
            root.find(`.xmap-exact-rows[data-sec="${sec}"]`).toggle();
        });
        root.on('input', '.xmap-search', function () {
            const sec = $(this).data('sec'), q = ($(this).val() || '').toLowerCase();
            root.find(`.xmap-card[data-sec="${sec}"] tbody tr[data-name]`).each(function () {
                $(this).toggle($(this).data('name').indexOf(q) !== -1);
            });
        });
        root.on('click', '.xmap-bulk', function (e) {
            e.preventDefault();
            const sec = $(this).data('sec'), bulk = $(this).data('bulk');
            root.find(`.xmap-card[data-sec="${sec}"] .xmap-action`).each(function () {
                const $tgt = root.find(`.xmap-target[data-sec="${sec}"][data-idx="${$(this).data('idx')}"]`);
                if (bulk === 'skip') { $(this).val('skip'); }
                else { $(this).val($tgt.find('option:selected').val() ? 'map' : ($(this).find('option[value="create"]').length ? 'create' : 'skip')); }
                $(this).trigger('change');
            });
        });
    }

    collect() {
        const out = { to_xero: [], from_xero: [], tax: [] };
        const root = this.content, ws = this.ws;
        root.find('.xmap-action').each(function () {
            const sec = $(this).data('sec'), idx = $(this).data('idx'), action = $(this).val();
            if (action === 'skip') return;
            const $tgt = root.find(`.xmap-target[data-sec="${sec}"][data-idx="${idx}"]`);
            const $opt = $tgt.find('option:selected');
            if (sec === 'to') {
                const u = ws.accounts_to_xero[idx];
                const e = { erpnext_account: u.erpnext_account, action };
                if (action === 'map') { if (!$tgt.val()) return; e.xero_account_code = $tgt.val(); e.xero_account_name = $opt.data('name') || ''; e.xero_account_id = $opt.data('id') || ''; }
                out.to_xero.push(e);
            } else if (sec === 'from') {
                const u = ws.accounts_from_xero[idx];
                const e = { xero_account_id: u.xero_account_id, xero_code: u.xero_code, xero_name: u.xero_name, xero_type: u.xero_type, action };
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

    apply() {
        const decisions = this.collect();
        const n = decisions.to_xero.length + decisions.from_xero.length + decisions.tax.length;
        if (!n) { frappe.show_alert({ message: __('Nothing selected to apply'), indicator: 'orange' }); return; }
        const createXero = decisions.to_xero.filter(x => x.action === 'create').length;
        frappe.confirm(
            __('Apply {0} change(s)? {1} account(s) may be created in Xero (existing ones are linked, never duplicated).', [n, createXero]),
            () => {
                frappe.call({
                    method: 'xero.utils.account_mapper.apply_mapping_workspace',
                    args: { decisions: JSON.stringify(decisions) },
                    freeze: true,
                    freeze_message: __('Applying mappings…'),
                    callback: (r) => {
                        const res = r.message || {};
                        const ob = res.outbound || {};
                        const errs = (res.errors || []).concat(ob.errors || []);
                        let msg = `<b>${(res.mapped || []).length}</b> linked/mapped · <b>${(res.created_erpnext || []).length}</b> created in ERPNext · <b>${(res.tax_mapped || []).length}</b> tax mapped.`;
                        if (ob.queued) msg += `<br><b>${ob.count}</b> account(s) reconciling with Xero in the background…`;
                        else if (ob.created || ob.mapped) msg += `<br><b>${(ob.created || []).length}</b> created in Xero · <b>${(ob.mapped || []).length}</b> linked to existing.`;
                        if (errs.length) { msg += `<br><br><b style="color:#c0392b;">${errs.length} issue(s):</b><ul style="margin:6px 0 0;padding-left:18px;max-height:220px;overflow:auto;">` + errs.map(e => `<li>${_esc(e)}</li>`).join('') + '</ul>'; }
                        frappe.msgprint({ title: __('Mapping applied'), message: msg, indicator: errs.length ? 'orange' : 'green' });
                        if (ob.queued) {
                            const on_done = (data) => { frappe.realtime.off('xero_resolve_done', on_done); frappe.show_alert({ message: __('Xero reconciliation finished: {0} created, {1} linked.', [(data.created || []).length, (data.mapped || []).length]), indicator: 'green' }, 8); this.load(); };
                            frappe.realtime.on('xero_resolve_done', on_done);
                        } else { this.load(); }
                    },
                    error: () => frappe.show_alert({ message: __('Failed to apply mappings'), indicator: 'red' }),
                });
            }
        );
    }
}

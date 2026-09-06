import { createApp } from "vue";
import XeroDashboardView from "./XeroDashboard.vue";

class XeroDashboard {
	constructor({ wrapper, page }) {
		this.page = page;
		this.app = createApp(XeroDashboardView);
		SetVueGlobals(this.app);
		this.component = this.app.mount($(wrapper).get(0));
	}

	refresh() {
		this.component?.load?.();
	}

	unmount() {
		this.app?.unmount();
	}
}

frappe.provide("frappe.ui");
frappe.ui.XeroDashboard = XeroDashboard;
export default XeroDashboard;

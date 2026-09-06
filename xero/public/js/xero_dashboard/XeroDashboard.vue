<template>
	<div class="xr">
		<!-- ===================== toolbar ===================== -->
		<div class="xr-toolbar">
			<div class="toolbar-title">
				<span class="dot" :style="{ background: overallColour }"></span>
				<strong>{{ __("Xero Sync") }}</strong>
			</div>
			<span class="pill" :class="overallTone">{{ overallLabel }}</span>
			<span class="pill" v-if="tenantName">{{ tenantName }}</span>

			<div class="toolbar-spacer"></div>

			<!-- The two directions are independent settings. Both stay visible so
			     nobody has to wonder why one side has gone quiet. -->
			<button
				class="dir-chip"
				:class="{ off: !conn.sync_to_xero_enabled }"
				:title="__('Enable Sync TO Xero, in Xero Settings')"
				@click="openSettings"
			>
				<span class="arrow">&#8594;</span> {{ __("To Xero") }}
				<span class="dot" :style="{ background: conn.sync_to_xero_enabled ? green : grey }"></span>
			</button>
			<button
				class="dir-chip"
				:class="{ off: !conn.sync_from_xero_enabled }"
				:title="__('Enable Sync FROM Xero, in Xero Settings')"
				@click="openSettings"
			>
				<span class="arrow">&#8592;</span> {{ __("From Xero") }}
				<span class="dot" :style="{ background: conn.sync_from_xero_enabled ? green : grey }"></span>
			</button>

			<div class="toolbar-divider"></div>

			<button class="tbtn" :disabled="!connected || !!busy" @click="syncAll">
				<Spin v-if="busy === 'sync-all'" />
				<svg v-else width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 1 1-2.6-6.4" /><path d="M21 3v6h-6" /></svg>
				{{ __("Sync all") }}
			</button>
			<button class="tbtn" @click="openLogs()">
				<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M8 6h13" /><path d="M8 12h13" /><path d="M8 18h13" /><path d="M3 6h.01" /><path d="M3 12h.01" /><path d="M3 18h.01" /></svg>
				{{ __("Logs") }}
			</button>
			<button class="tbtn icon-only" :title="__('Refresh')" :disabled="loading" @click="load">
				<Spin v-if="loading" />
				<svg v-else width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 0 1 15-6.7L21 8" /><path d="M21 3v5h-5" /><path d="M21 12a9 9 0 0 1-15 6.7L3 16" /><path d="M3 21v-5h5" /></svg>
			</button>
		</div>

		<div class="xr-body">
			<!-- ===================== rail ===================== -->
			<div class="rail">
				<div class="rail-scroll">
					<h6>{{ __("Connection") }}</h6>
					<div class="rail-row" :class="{ on: !selectedRun }" @click="selectedRun = null">
						<span class="dot" :style="{ background: connected ? green : red }"></span>
						<div class="rail-text">
							<strong>{{ tenantName || __("Not connected") }}</strong>
							<small v-if="conn.tenant_id">{{ shortId(conn.tenant_id) }}</small>
						</div>
					</div>

					<h6 v-if="entities.length">{{ __("Entities") }} &middot; {{ entities.length }}</h6>
					<div
						v-for="e in entities"
						:key="e.entity"
						class="ent"
						:class="{ on: selectedEntity === e.entity }"
						@click="pickEntity(e)"
					>
						<div class="ent-name">{{ __(e.entity) }}</div>
						<div class="ent-rate" :class="{ bad: e.errors > 0 }">
							{{ e.errors > 0 ? e.errors + " " + __("failing") : Math.round(e.sync_rate) + "%" }}
						</div>
					</div>
				</div>
			</div>

			<!-- ===================== centre ===================== -->
			<div class="centre">
				<!-- --- run drill-in --- -->
				<template v-if="selectedRun">
					<div class="crumb">
						<a href="#" @click.prevent="selectedRun = null">
							<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 12H5" /><path d="m12 19-7-7 7-7" /></svg>
							{{ __("Sync activity") }}
						</a>
					</div>
					<div class="runhead">
						<h2>{{ runTitle(selectedRun) }}</h2>
						<span class="status" :class="statusClass(selectedRun.overall_status)">
							<span class="status-dot"></span> {{ __(selectedRun.overall_status) }}
						</span>
						<div class="toolbar-spacer"></div>
						<span class="muted">
							{{ ago(selectedRun.sync_time) }}
							<template v-if="selectedRun.duration"> &middot; {{ secs(selectedRun.duration) }}</template>
							<template v-if="selectedRun.sync_batch_id"> &middot; {{ __("batch") }} {{ shortId(selectedRun.sync_batch_id, 6) }}</template>
						</span>
					</div>

					<div class="centre-scroll tight">
						<div class="panel grow">
							<div class="panel-head">
								<strong>{{ __("Items") }}</strong>
								<span class="muted">{{ (selectedRun.items || []).length }}</span>
								<div class="toolbar-spacer"></div>
								<button
									v-if="runFailures(selectedRun).length"
									class="tbtn small"
									:class="{ on: failuresOnly }"
									@click="failuresOnly = !failuresOnly"
								>
									{{ __("Failures only") }}
								</button>
								<button
									v-if="runFailures(selectedRun).length"
									class="tbtn small primary"
									:disabled="!!busy"
									@click="retryLogs(runFailures(selectedRun).map((i) => i.log_name))"
								>
									<Spin v-if="busy === 'retry'" />
									{{ __("Retry") }} {{ runFailures(selectedRun).length }}
								</button>
							</div>

							<div v-if="!visibleItems.length" class="empty">{{ __("No items logged for this run.") }}</div>
							<div
								v-for="item in visibleItems"
								:key="item.log_name"
								class="item"
								:class="{ bad: item.status === 'Error' }"
								@click="openLogDoc(item.log_name)"
							>
								<div>
									<span class="status" :class="statusClass(item.status)">
										<span class="status-dot"></span> {{ __(item.status) }}
									</span>
								</div>
								<div class="item-doc">
									{{ item.erpnext_doc_name }}
									<em v-if="item.erpnext_doc_type"> &middot; {{ __(item.erpnext_doc_type) }}</em>
								</div>
								<div class="item-msg" :class="{ bad: item.status === 'Error' }">{{ item.message }}</div>
								<div class="item-ms">{{ ms(item.processing_time) }}</div>
							</div>
						</div>
					</div>
				</template>

				<!-- --- dashboard --- -->
				<template v-else>
					<div v-if="banner" class="banner" :class="banner.tone">
						<svg width="18" height="18" viewBox="0 0 24 24" fill="none" :stroke="banner.stroke" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
							<circle cx="12" cy="12" r="9" />
							<path v-if="banner.tone === 'warn'" d="M12 7v5l3 2" />
							<template v-else><path d="M12 8v5" /><path d="M12 16h.01" /></template>
						</svg>
						<div class="banner-text">
							<strong>{{ banner.title }}</strong>
							<span>{{ banner.text }}</span>
						</div>
						<button class="tbtn" :disabled="!!busy" @click="banner.act">
							<Spin v-if="busy === 'reconnect'" />
							{{ banner.label }}
						</button>
					</div>

					<div class="centre-scroll" :class="{ tight: !banner }">
						<div class="panel">
							<div class="panel-head">
								<strong>{{ __("Needs attention") }}</strong>
								<span v-if="attention.length" class="muted">{{ attention.length }}</span>
								<div class="toolbar-spacer"></div>
								<a href="#" @click.prevent="openLogs()">{{ __("Xero Logs") }}</a>
							</div>

							<div v-if="loading" class="empty">{{ __("Checking…") }}</div>
							<div v-else-if="!attention.length" class="empty">
								<!-- "Nothing needs attention" under a red not-connected banner reads
								     as a contradiction; there is simply nothing to report yet. -->
								<template v-if="!connected">
									{{ __("Nothing to report until Xero is connected.") }}
								</template>
								<template v-else>
									{{ __("Nothing needs attention.") }}
									<template v-if="coverage.synced">
										{{ coverage.synced.toLocaleString() }} {{ __("records all carry a Xero ID.") }}
									</template>
								</template>
							</div>

							<div v-for="(a, i) in attention" :key="a.key" class="attn">
								<div class="attn-count">{{ a.count }}</div>
								<div class="attn-text">
									<strong>{{ a.title }}</strong>
									<span>{{ a.detail }}</span>
								</div>
								<span class="chip" :class="a.severity">{{ __(a.severity) }}</span>
								<button
									class="tbtn"
									:class="{ primary: i === 0 || a.action.primary }"
									:disabled="!!busy"
									@click="runAction(a.action)"
								>
									<Spin v-if="busy === a.key" />
									{{ a.action.label }}
								</button>
							</div>
						</div>

						<div class="panel grow">
							<div class="panel-head">
								<strong>{{ __("Sync activity") }}</strong>
								<span class="muted">{{ __("last 7 days") }}</span>
								<div class="toolbar-spacer"></div>
								<a href="#" @click.prevent="openLogs()">{{ __("All runs") }}</a>
							</div>

							<div v-if="loading" class="empty">{{ __("Loading…") }}</div>
							<div v-else-if="!runs.length" class="empty">{{ __("No sync has run in the last seven days.") }}</div>

							<div v-for="run in runs" :key="runKey(run)" class="run" @click="openRun(run)">
								<div class="run-when">{{ ago(run.sync_time) }}</div>
								<div class="run-dir">
									<span class="arrow">{{ inbound(run) ? "&#8592;" : "&#8594;" }}</span>
									{{ inbound(run) ? __("From Xero") : __("To Xero") }}
								</div>
								<div class="run-what">{{ (run.entities_synced || []).join(", ") || __("Unknown") }}</div>
								<div class="run-counts">
									<template v-if="run.success_count">{{ run.success_count }} {{ __("ok") }}</template>
									<template v-if="run.success_count && run.error_count"> &middot; </template>
									<b v-if="run.error_count">{{ run.error_count }} {{ __("failed") }}</b>
									<template v-if="run.warning_count">
										<template v-if="run.success_count || run.error_count"> &middot; </template>
										{{ run.warning_count }} {{ run.warning_count === 1 ? __("warning") : __("warnings") }}
									</template>
								</div>
								<div>
									<span class="status" :class="statusClass(run.overall_status)">
										<span class="status-dot"></span> {{ __(run.overall_status) }}
									</span>
								</div>
							</div>
						</div>
					</div>
				</template>
			</div>

			<!-- ===================== detail ===================== -->
			<div class="detail">
				<!-- --- run detail --- -->
				<template v-if="selectedRun">
					<div class="detail-head">
						<div class="pair">
							<strong>{{ __("This run") }}</strong>
							<span v-if="selectedRun.error_count" class="pill bad">
								{{ selectedRun.error_count }} {{ __("failed") }}
							</span>
							<span v-else class="pill ok">{{ __("Clean") }}</span>
						</div>
						<div v-if="selectedRun.sync_batch_id" class="realm">
							{{ __("batch") }} {{ selectedRun.sync_batch_id }}
						</div>
					</div>

					<div class="detail-scroll">
						<h6 class="flush">{{ __("Outcome") }}</h6>
						<div class="summary-line"><span>{{ __("Succeeded") }}</span><b class="good">{{ selectedRun.success_count || 0 }}</b></div>
						<div class="summary-line"><span>{{ __("Failed") }}</span><b :class="{ bad: selectedRun.error_count }">{{ selectedRun.error_count || 0 }}</b></div>
						<div class="summary-line"><span>{{ __("Warnings") }}</span><b :class="{ warn: selectedRun.warning_count }">{{ selectedRun.warning_count || 0 }}</b></div>
						<div v-if="selectedRun.skipped_count" class="summary-line"><span>{{ __("Skipped") }}</span><b>{{ selectedRun.skipped_count }}</b></div>
						<div v-if="selectedRun.duration" class="summary-line"><span>{{ __("Duration") }}</span><b>{{ secs(selectedRun.duration) }}</b></div>

						<template v-if="(selectedRun.failure_summary || []).length">
							<h6 class="flush">{{ __("Why it failed") }}</h6>
							<div v-for="f in selectedRun.failure_summary" :key="f.failure_category" class="summary-line">
								<span>{{ __(f.failure_category) }}</span><b>{{ f.count }}</b>
							</div>
						</template>

						<template v-if="(selectedRun.actionable_recommendations || []).length">
							<h6 class="flush">{{ __("What to do") }}</h6>
							<div v-for="(r, i) in selectedRun.actionable_recommendations" :key="i" class="rec">
								<div class="rec-head">
									<strong>{{ r.title }}</strong>
									<span class="chip" :class="r.severity">{{ __(r.severity) }}</span>
								</div>
								<p>{{ r.message }}</p>
								<p v-if="r.action" class="rec-do">{{ r.action }}</p>
								<div class="pair-buttons">
									<!-- Only the leading recommendation gets the solid button; two
									     stacked black buttons compete for the same click. -->
									<button
										v-if="r.action_button"
										class="tbtn bordered"
										:class="{ solid: i === 0 }"
										@click="goRoute(r.action_button.route)"
									>
										{{ r.action_button.label }}
									</button>
									<button
										v-if="r.secondary_button"
										class="tbtn bordered"
										@click="openLogs(r.secondary_button.filter)"
									>
										{{ r.secondary_button.label }}
									</button>
								</div>
							</div>
						</template>
					</div>
				</template>

				<!-- --- connection detail --- -->
				<template v-else>
					<div class="detail-head">
						<div class="pair">
							<strong>{{ tenantName || __("Xero") }}</strong>
							<span class="pill" :class="connected ? 'ok' : 'bad'">
								{{ connected ? __("Connected") : __("Not connected") }}
							</span>
						</div>
						<div v-if="conn.tenant_id" class="realm">{{ __("tenant") }} {{ conn.tenant_id }}</div>
					</div>

					<div class="detail-scroll">
						<h6 class="flush">{{ __("Authorisation") }}</h6>

						<div v-if="accessLeft !== null" class="meter">
							<div class="meter-head">
								<span>{{ __("Access token") }}</span>
								<strong :class="{ bad: accessLeft <= 0 }">{{ accessLabel }}</strong>
							</div>
							<div class="track">
								<div class="fill" :style="{ width: pct(accessLeft, 30) + '%', background: accessLeft <= 0 ? red : green }"></div>
							</div>
						</div>

						<div v-if="refreshLeft !== null" class="meter">
							<div class="meter-head">
								<span>{{ __("Refresh token") }}</span>
								<strong :class="{ bad: refreshLeft <= 10 }">
									{{ Math.max(refreshLeft, 0) }} {{ __("of 60 days") }}
								</strong>
							</div>
							<div class="track">
								<div class="fill" :style="{ width: pct(refreshLeft, 60) + '%', background: refreshTint }"></div>
							</div>
						</div>
						<p v-if="accessLeft === null && refreshLeft === null" class="coverage">
							{{ __("No token on record. Authorise from Xero Settings.") }}
						</p>

						<div class="pair-buttons">
							<button class="tbtn bordered" :disabled="!connected || !!busy" @click="testConnection">
								<Spin v-if="busy === 'test'" />
								{{ __("Test connection") }}
							</button>
							<button class="tbtn bordered" :disabled="!!busy" @click="reconnect">
								<Spin v-if="busy === 'reconnect'" />
								{{ __("Reconnect") }}
							</button>
						</div>

						<h6 class="flush">{{ __("Last run") }}</h6>
						<div class="fact"><span>{{ __("Finished") }}</span><strong>{{ ago(conn.last_sync) }}</strong></div>
						<div v-if="lastRun && lastRun.duration" class="fact"><span>{{ __("Duration") }}</span><strong>{{ secs(lastRun.duration) }}</strong></div>
						<div v-if="health.status" class="fact"><span>{{ __("Health") }}</span><strong>{{ __(health.status) }} &middot; {{ health.score }}</strong></div>
						<div v-if="health.success_rate !== undefined" class="fact"><span>{{ __("Success rate, 24h") }}</span><strong>{{ health.success_rate }}%</strong></div>
						<div class="fact"><span>{{ __("Stuck jobs") }}</span><strong>{{ health.stuck_jobs || __("none") }}</strong></div>

						<div v-if="topError" class="error">{{ topError }}</div>

						<h6 class="flush">{{ __("Direction") }}</h6>
						<div class="flag">
							<span class="dot" :style="{ background: conn.sync_to_xero_enabled ? green : grey }"></span>
							<span :class="{ muted: !conn.sync_to_xero_enabled }">{{ __("To Xero") }}</span>
							<em>{{ conn.sync_to_xero_enabled ? scheduleLabel : __("off") }}</em>
						</div>
						<div class="flag">
							<span class="dot" :style="{ background: conn.sync_from_xero_enabled ? green : grey }"></span>
							<span :class="{ muted: !conn.sync_from_xero_enabled }">{{ __("From Xero") }}</span>
							<em>{{ conn.sync_from_xero_enabled ? scheduleLabel : __("off") }}</em>
						</div>

						<template v-if="coverage.total">
							<h6 class="flush">{{ __("Coverage") }}</h6>
							<p class="coverage">
								{{ coverage.synced.toLocaleString() }} {{ __("of") }}
								{{ coverage.total.toLocaleString() }} {{ __("records carry a Xero ID") }} &mdash;
								{{ coverage.pct }}%.
								{{ failing.length ? countSentence(failing.length) : __("Nothing failing.") }}
							</p>
							<div v-for="e in failing" :key="e.entity" class="failing" @click="pickEntity(e)">
								<span>{{ __(e.entity) }}</span>
								<b>{{ e.errors }}</b>
							</div>
						</template>
					</div>
				</template>
			</div>
		</div>

		<!-- ===================== map accounts ===================== -->
		<Teleport to="body">
			<MapAccountsDialog v-if="mapOpen" @close="mapOpen = false" @mapped="onMapped" />
		</Teleport>
	</div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from "vue";
import MapAccountsDialog from "./MapAccountsDialog.vue";
import Spin from "./Spin.vue";

const API = "xero.xero.page.xero_sync_dashboard.xero_sync_dashboard.";

const green = "var(--green-500)";
const red = "var(--red-500)";
const amber = "var(--yellow-500)";
const grey = "var(--gray-400)";

const loading = ref(true);
const busy = ref("");
const conn = ref({});
const entities = ref([]);
const health = ref({});
const recentErrors = ref([]);
const attention = ref([]);
const runs = ref([]);
const selectedRun = ref(null);
const selectedEntity = ref(null);
const failuresOnly = ref(false);
const mapOpen = ref(false);
let timer = null;

/* ---------------------------------------------------------------- loading */

const call = (method, args) => frappe.xcall(API + method, args);

async function load() {
	loading.value = true;
	// Three independent reads; a slow one must not hold up the rest, and any
	// one of them failing must not blank the page.
	const [overview, attn, attempts] = await Promise.all([
		call("get_dashboard_overview").catch(() => ({})),
		call("get_attention_items").catch(() => ({ items: [] })),
		call("get_last_sync_attempts").catch(() => ({ sync_attempts: [] })),
	]);

	conn.value = overview.connection || {};
	entities.value = overview.entity_status || [];
	health.value = overview.health || {};
	recentErrors.value = (overview.recent_errors && overview.recent_errors.errors) || [];
	attention.value = attn.items || [];
	runs.value = attempts.sync_attempts || [];

	// Keep the drill-in pinned to the same run across a refresh.
	if (selectedRun.value) {
		const key = runKey(selectedRun.value);
		selectedRun.value = runs.value.find((r) => runKey(r) === key) || null;
	}
	loading.value = false;
}

onMounted(() => {
	load();
	timer = setInterval(() => {
		if (!busy.value && !document.hidden) load();
	}, 60000);
});
onUnmounted(() => clearInterval(timer));

/* ------------------------------------------------------------- derivation */

const connected = computed(() => !!conn.value.connected);

// The controller falls back to the literal string "Not Connected" for an
// unauthorised site; rendering that as an organisation name put the same words
// in the toolbar twice.
const tenantName = computed(() => {
	const name = conn.value.tenant_name;
	return connected.value && name && name !== "Not Connected" ? name : "";
});

// Token timestamps come back in SYSTEM time, so they have to be compared with
// system_datetime() — now_datetime() is the user's timezone and would skew both
// meters by the offset between the two.
const minutesUntil = (value) =>
	value ? frappe.datetime.get_minute_diff(value, frappe.datetime.system_datetime()) : null;
const daysUntil = (value) =>
	value ? frappe.datetime.get_diff(value, frappe.datetime.system_datetime()) : null;

const accessLeft = computed(() => minutesUntil(conn.value.token_expiry));
const refreshLeft = computed(() => daysUntil(conn.value.refresh_token_expiry));

const accessLabel = computed(() => {
	const m = accessLeft.value;
	if (m === null) return "";
	if (m <= 0) return __("expired");
	if (m < 60) return `${m} ${__("min left")}`;
	return `${Math.floor(m / 60)} ${__("hr left")}`;
});

const refreshTint = computed(() => {
	const d = refreshLeft.value;
	if (d === null) return grey;
	if (d <= 10) return red;
	if (d <= 21) return amber;
	return green;
});

const pct = (left, of) => Math.max(0, Math.min(100, Math.round(((left || 0) / of) * 100)));

const coverage = computed(() => {
	const total = entities.value.reduce((n, e) => n + (e.total || 0), 0);
	const synced = entities.value.reduce((n, e) => n + (e.synced || 0), 0);
	return { total, synced, pct: total ? Math.round((synced / total) * 100) : 0 };
});

const failing = computed(() => entities.value.filter((e) => e.errors > 0));

const overallLabel = computed(() => {
	if (loading.value && !entities.value.length) return __("Loading");
	if (!connected.value) return __("Not connected");
	if (attention.value.length) return __("Needs attention");
	return __("Healthy");
});
const overallTone = computed(() => {
	if (!connected.value) return "bad";
	if (attention.value.length) return "warn";
	return "ok";
});
const overallColour = computed(() => {
	if (!connected.value) return red;
	if (attention.value.length) return amber;
	return green;
});

// One banner, for the thing that stops everything else working.
const banner = computed(() => {
	if (!connected.value) {
		return {
			tone: "bad",
			stroke: "oklch(0.55 0.16 25)",
			title: __("Xero is not connected"),
			text: __("Nothing will sync in either direction until someone authorises this site against a Xero organisation."),
			label: __("Connect"),
			act: openSettings,
		};
	}
	const d = refreshLeft.value;
	if (d !== null && d <= 14) {
		return {
			tone: d <= 3 ? "bad" : "warn",
			stroke: d <= 3 ? "oklch(0.55 0.16 25)" : "oklch(0.55 0.13 75)",
			title:
				d <= 0
					? __("Refresh token has expired")
					: `${__("Refresh token expires in")} ${d} ${d === 1 ? __("day") : __("days")}`,
			text: __(
				"Xero refresh tokens last 60 days and roll forward on every call. Re-authorise before then or every sync stops until someone signs in again."
			),
			label: __("Reconnect"),
			act: reconnect,
		};
	}
	return null;
});

const lastRun = computed(() => runs.value[0] || null);

const topError = computed(() => {
	const first = recentErrors.value[0];
	if (!first) return "";
	const doc = first.erpnext_doc_name && first.erpnext_doc_name !== "Unknown" ? `${first.erpnext_doc_name}: ` : "";
	return doc + first.message;
});

const scheduleLabel = computed(() => {
	if (!conn.value.auto_sync) return __("manual");
	return conn.value.sync_frequency ? __(conn.value.sync_frequency) : __("scheduled");
});

const visibleItems = computed(() => {
	const items = (selectedRun.value && selectedRun.value.items) || [];
	return failuresOnly.value ? items.filter((i) => i.status === "Error") : items;
});

/* ------------------------------------------------------------ formatting */

// comment_when() returns markup, which a text binding escapes and prints raw;
// prettyDate() is plain text but too long ("42 minutes ago") for an 84px column.
function ago(value) {
	if (!value) return __("never");
	const mins = frappe.datetime.get_minute_diff(frappe.datetime.system_datetime(), value);
	if (mins < 1) return __("just now");
	if (mins < 60) return `${mins} ${__("min ago")}`;
	const hrs = Math.floor(mins / 60);
	if (hrs < 24) return `${hrs} ${hrs === 1 ? __("hr") : __("hrs")} ${__("ago")}`;
	const days = Math.floor(hrs / 24);
	if (days < 7) return `${days} ${days === 1 ? __("day") : __("days")} ${__("ago")}`;
	return frappe.datetime.str_to_user(value).split(" ")[0];
}
const secs = (d) => `${Number(d).toFixed(1)}s`;
const ms = (t) => (t ? `${Math.round(Number(t) * 1000)}ms` : "");
const shortId = (id, keep = 8) => (id && id.length > keep * 2 ? `${id.slice(0, keep)}…${id.slice(-4)}` : id);
const countSentence = (n) => `${n} ${n === 1 ? __("entity is failing.") : __("entities are failing.")}`;

// Xero Log's own values are "ERPNext to Xero" and "Xero to ERPNext"; older rows
// and the batch roll-up also use "From Xero"/"Inbound".
const inbound = (run) => {
	const d = (run.sync_direction || "").toLowerCase();
	return d.startsWith("xero to") || d.includes("from xero") || d === "inbound";
};
const runTitle = (run) => {
	const what = (run.entities_synced || []).join(", ") || __("Sync");
	return inbound(run) ? `${what} ${"←"} Xero` : `${what} ${"→"} Xero`;
};
const runKey = (run) => run.sync_batch_id || `${run.sync_time}|${run.sync_direction}`;
const runFailures = (run) => (run.items || []).filter((i) => i.status === "Error" && i.log_name);

const statusClass = (status) => {
	const s = (status || "").toLowerCase();
	if (s === "error" || s === "failed") return "fail";
	if (s.includes("partial") || s === "warning" || s.includes("warnings only")) return "partial";
	return "ok";
};

/* --------------------------------------------------------------- actions */

function openSettings() {
	frappe.set_route("Form", "Xero Settings");
}
function goRoute(route) {
	if (!route) return;
	if (Array.isArray(route)) frappe.set_route(...route);
	else frappe.set_route(route.replace(/^\/app\//, ""));
}
function openLogs(filters) {
	frappe.route_options = filters || undefined;
	frappe.set_route("List", "Xero Log");
}
function openLogDoc(name) {
	if (name) frappe.set_route("Form", "Xero Log", name);
}
function openRun(run) {
	failuresOnly.value = false;
	selectedRun.value = run;
}
function pickEntity(e) {
	selectedEntity.value = selectedEntity.value === e.entity ? null : e.entity;
	openLogs({ erpnext_doc_type: e.entity });
}

async function guard(key, fn, done) {
	if (busy.value) return;
	busy.value = key;
	try {
		const result = await fn();
		if (result && result.success === false) {
			frappe.msgprint({
				title: __("Xero"),
				message: result.error || __("The call did not succeed."),
				indicator: "red",
			});
		} else if (done) {
			done(result);
		}
		await load();
	} catch (e) {
		// frappe.xcall already surfaces the server traceback.
	} finally {
		busy.value = "";
	}
}

const testConnection = () =>
	guard("test", () => call("test_xero_connection"), (r) =>
		frappe.show_alert({
			message: `${__("Connected to")} ${r.organisation || tenantName.value || __("Xero")}`,
			indicator: "green",
		})
	);

const reconnect = () =>
	guard("reconnect", () => call("refresh_xero_token"), (r) => {
		if (r && r.success) {
			frappe.show_alert({ message: __("Token refreshed"), indicator: "green" });
		}
	}).then(() => {
		// A refresh only works while the refresh token is alive; once it is not,
		// the fix is a full re-authorisation from Settings.
		if (!conn.value.connected || (refreshLeft.value !== null && refreshLeft.value <= 0)) {
			frappe.msgprint({
				title: __("Re-authorise Xero"),
				message: __("The refresh token can no longer be used. Reconnect from Xero Settings to sign in again."),
				primary_action: { label: __("Xero Settings"), action: openSettings },
			});
		}
	});

const syncAll = () =>
	guard("sync-all", () => call("sync_all_entities"), () =>
		frappe.show_alert({ message: __("Sync queued for every enabled entity"), indicator: "blue" })
	);

const retryLogs = (names) =>
	guard("retry", async () => {
		for (const name of names) await call("retry_failed_job", { log_name: name });
		return { success: true };
	}, () => frappe.show_alert({ message: `${names.length} ${__("queued for retry")}`, indicator: "blue" }));

function runAction(action) {
	if (!action) return;
	switch (action.kind) {
		case "map_accounts":
			mapOpen.value = true;
			break;
		case "reconnect":
			reconnect();
			break;
		case "sync_entity":
			guard("sync-entity", () => call("trigger_manual_sync", { entity_type: action.entity }), () =>
				frappe.show_alert({ message: `${__("Sync queued:")} ${action.entity}`, indicator: "blue" })
			);
			break;
		case "retry":
			retryLogs(action.log_names || []);
			break;
		case "open_doc":
			frappe.set_route("Form", action.doctype, action.name);
			break;
		case "route":
			goRoute(action.route);
			break;
		case "logs":
		default:
			openLogs(action.filters);
	}
}

function onMapped(result) {
	mapOpen.value = false;
	if (result && result.mapped) {
		frappe.show_alert({
			message: `${result.mapped} ${result.mapped === 1 ? __("account mapped") : __("accounts mapped")}`,
			indicator: "green",
		});
	}
	load();
}

defineExpose({ load });
</script>

<style scoped>
/* The Automation Builder / QuickBooks shell, so the integrations read as one
   product: 54px toolbar, 252 / 1fr / 336 body, Frappe's own tokens. */
.xr {
	height: calc(100vh - 120px);
	min-height: 620px;
	overflow: hidden;
	background: var(--card-bg);
	display: flex;
	flex-direction: column;
}
.xr-toolbar {
	height: 54px;
	flex: none;
	display: flex;
	align-items: center;
	gap: 4px;
	padding: 0 12px;
	border-bottom: 1px solid var(--border-color);
	background: var(--fg-color);
}
.toolbar-title {
	display: flex;
	align-items: center;
	gap: 8px;
	margin-left: 4px;
	font-size: 14px;
}
.toolbar-title strong {
	font-weight: 600;
}
.toolbar-spacer {
	flex: 1;
}
.toolbar-divider {
	width: 1px;
	height: 22px;
	background: var(--border-color);
	margin: 0 4px;
}
.pill {
	font-size: 11px;
	font-weight: 700;
	padding: 2px 8px;
	border-radius: 999px;
	background: var(--control-bg);
	color: var(--text-muted);
	white-space: nowrap;
}
.pill.warn {
	background: var(--yellow-100);
	color: var(--yellow-600);
}
.pill.ok {
	background: var(--green-100);
	color: var(--green-600);
}
.pill.bad {
	background: var(--red-100);
	color: var(--red-600);
}
.tbtn {
	display: flex;
	align-items: center;
	gap: 6px;
	height: 32px;
	padding: 0 10px;
	border-radius: 7px;
	font-size: 12.5px;
	font-weight: 600;
	color: var(--text-color);
	background: transparent;
	border: 0;
	cursor: pointer;
	white-space: nowrap;
	font-family: inherit;
}
.tbtn:hover {
	background: var(--control-bg);
}
.tbtn.icon-only {
	width: 32px;
	padding: 0;
	justify-content: center;
}
.tbtn.primary {
	background: var(--primary);
	color: white;
}
.tbtn.primary:hover {
	opacity: 0.9;
}
.tbtn.bordered {
	flex: 1;
	justify-content: center;
	border: 1px solid var(--border-color);
	border-radius: 8px;
	background: var(--card-bg);
	font-size: 12px;
}
.tbtn.bordered.solid {
	background: var(--primary);
	color: white;
	border-color: var(--primary);
}
.tbtn.small {
	height: 26px;
	padding: 0 10px;
	font-size: 11.5px;
	border: 1px solid var(--border-color);
}
.tbtn.small.on {
	background: var(--control-bg);
}
.tbtn[disabled] {
	opacity: 0.35;
	pointer-events: none;
}

/* Xero's two sync directions are independent settings; both stay on screen. */
.dir-chip {
	display: flex;
	align-items: center;
	gap: 6px;
	height: 26px;
	padding: 0 9px;
	border: 1px solid var(--border-color);
	border-radius: 999px;
	font-size: 11.5px;
	font-weight: 500;
	color: var(--text-color);
	background: var(--card-bg);
	cursor: pointer;
	font-family: inherit;
}
.dir-chip:hover {
	border-color: var(--gray-400);
}
.dir-chip .arrow {
	font-size: 12px;
	color: var(--text-light);
}
.dir-chip.off {
	color: var(--text-light);
	background: var(--control-bg);
	border-color: var(--control-bg);
}

.xr-body {
	flex: 1;
	display: grid;
	grid-template-columns: 252px 1fr 336px;
	min-height: 0;
}

/* rail */
.rail {
	border-right: 1px solid var(--border-color);
	background: var(--fg-color);
	display: flex;
	flex-direction: column;
	min-height: 0;
}
.rail-scroll {
	flex: 1;
	overflow: auto;
	padding: 0 8px 12px;
}
h6 {
	margin: 14px 6px 4px;
	font-size: 10.5px;
	font-weight: 700;
	letter-spacing: 0.05em;
	text-transform: uppercase;
	color: var(--text-muted);
}
h6.flush {
	margin-left: 0;
	margin-right: 0;
}
.rail-row {
	display: flex;
	gap: 8px;
	align-items: center;
	padding: 8px;
	margin: 2px 0;
	border-radius: 8px;
	cursor: pointer;
}
.rail-row:hover,
.rail-row.on {
	background: var(--control-bg);
}
.rail-row.on .rail-text strong {
	font-weight: 600;
}
.dot {
	width: 7px;
	height: 7px;
	border-radius: 999px;
	flex: none;
}
.rail-text {
	min-width: 0;
	flex: 1;
}
.rail-text strong {
	display: block;
	font-size: 12.5px;
	font-weight: 400;
	color: var(--text-color);
}
.rail-text small {
	display: block;
	font-size: 10.5px;
	color: var(--text-muted);
	font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
	overflow: hidden;
	text-overflow: ellipsis;
	white-space: nowrap;
}
/* Entity rows carry a number, not a bar: eleven meters all sitting at 95-100%
   coloured the rail without saying anything the count does not already say. */
.ent {
	display: flex;
	align-items: center;
	gap: 8px;
	padding: 8px;
	margin: 1px 0;
	border-radius: 8px;
	cursor: pointer;
}
.ent:hover,
.ent.on {
	background: var(--control-bg);
}
.ent-name {
	flex: 1;
	min-width: 0;
	font-size: 12px;
	color: var(--text-color);
	overflow: hidden;
	text-overflow: ellipsis;
	white-space: nowrap;
}
.ent-rate {
	flex: none;
	font-size: 10.5px;
	color: var(--text-muted);
	font-variant-numeric: tabular-nums;
}
.ent-rate.bad {
	color: var(--red-600);
	font-weight: 600;
}

/* centre */
.centre {
	min-width: 0;
	background: var(--fg-color);
	display: flex;
	flex-direction: column;
	min-height: 0;
}
.banner {
	flex: none;
	display: flex;
	align-items: center;
	gap: 12px;
	margin: 16px 16px 0;
	padding: 12px 14px;
	border-radius: 10px;
}
.banner.bad {
	background: oklch(0.96 0.03 25);
	border: 1px solid oklch(0.88 0.06 25);
}
.banner.warn {
	background: oklch(0.975 0.035 90);
	border: 1px solid oklch(0.9 0.07 90);
}
.banner svg {
	flex: none;
}
.banner-text {
	flex: 1;
	min-width: 0;
}
.banner-text strong {
	display: block;
	font-size: 13px;
	font-weight: 600;
}
.banner.bad .banner-text strong {
	color: oklch(0.4 0.14 25);
}
.banner.warn .banner-text strong {
	color: oklch(0.42 0.11 75);
}
.banner-text span {
	display: block;
	margin-top: 2px;
	font-size: 11.5px;
	color: var(--text-muted);
	text-wrap: pretty;
}
.banner .tbtn {
	flex: none;
	border: 1px solid var(--border-color);
	background: var(--card-bg);
}
.centre-scroll {
	flex: 1;
	overflow: auto;
	padding: 14px 16px 16px;
	display: flex;
	flex-direction: column;
	gap: 14px;
	min-height: 0;
}
.centre-scroll.tight {
	padding-top: 16px;
}
.panel {
	border: 1px solid var(--border-color);
	border-radius: 10px;
	overflow: hidden;
	flex: none;
}
.panel.grow {
	flex: 1;
	min-height: 200px;
	display: flex;
	flex-direction: column;
	overflow: auto;
}
.panel-head {
	display: flex;
	align-items: center;
	gap: 8px;
	padding: 11px 14px;
	border-bottom: 1px solid var(--border-color);
	font-size: 12.5px;
	flex: none;
	position: sticky;
	top: 0;
	background: var(--fg-color);
	z-index: 1;
}
.panel-head strong {
	font-weight: 600;
}
.muted {
	font-size: 11.5px;
	color: var(--text-muted);
}
.panel-head a {
	font-size: 11.5px;
	font-weight: 600;
	color: var(--primary);
}
.empty {
	padding: 34px 14px;
	text-align: center;
	font-size: 12.5px;
	color: var(--text-muted);
}

/* attention */
.attn {
	display: flex;
	align-items: center;
	gap: 12px;
	padding: 11px 14px;
	border-top: 1px solid var(--control-bg);
}
.attn:first-of-type {
	border-top: 0;
}
.attn-count {
	width: 30px;
	text-align: right;
	font-size: 15px;
	font-weight: 700;
	flex: none;
	font-variant-numeric: tabular-nums;
}
.attn-text {
	flex: 1;
	min-width: 0;
}
.attn-text strong {
	display: block;
	font-size: 12.5px;
	font-weight: 600;
	color: var(--text-color);
}
.attn-text span {
	display: block;
	margin-top: 1px;
	font-size: 11.5px;
	color: var(--text-muted);
	text-wrap: pretty;
}
.chip {
	font-size: 10.5px;
	font-weight: 600;
	padding: 2px 8px;
	border-radius: 999px;
	background: var(--control-bg);
	color: var(--text-muted);
	flex: none;
	text-transform: lowercase;
}
.chip.high {
	background: var(--red-100);
	color: var(--red-600);
}
.chip.medium {
	background: var(--yellow-100);
	color: var(--yellow-600);
}
.attn .tbtn {
	height: 28px;
	padding: 0 11px;
	font-size: 11.5px;
	flex: none;
	border: 1px solid var(--border-color);
}
.attn .tbtn.primary {
	border-color: var(--primary);
}

/* sync activity */
.run {
	display: grid;
	grid-template-columns: 84px 84px 1fr 160px 132px;
	gap: 12px;
	align-items: center;
	padding: 9px 14px;
	border-top: 1px solid var(--control-bg);
	cursor: pointer;
}
.run:hover {
	background: var(--gray-50);
}
.run-when {
	font-size: 11.5px;
	color: var(--text-muted);
}
.run-dir {
	display: flex;
	align-items: center;
	gap: 5px;
	font-size: 11px;
	font-weight: 600;
	color: var(--text-muted);
}
.run-dir .arrow {
	font-size: 12px;
}
.run-what {
	font-size: 11.5px;
	color: var(--text-color);
	overflow: hidden;
	text-overflow: ellipsis;
	white-space: nowrap;
}
.run-counts {
	font-size: 11.5px;
	color: var(--text-muted);
	font-variant-numeric: tabular-nums;
}
.run-counts b {
	font-weight: 600;
	color: var(--red-600);
}
.status {
	display: inline-flex;
	align-items: center;
	gap: 5px;
	font-size: 10.5px;
	font-weight: 600;
	padding: 2px 8px;
	border-radius: 999px;
	white-space: nowrap;
}
.status-dot {
	width: 5px;
	height: 5px;
	border-radius: 999px;
	background: currentColor;
}
.status.ok {
	background: var(--green-100);
	color: var(--green-600);
}
.status.partial {
	background: var(--yellow-100);
	color: var(--yellow-600);
}
.status.fail {
	background: var(--red-100);
	color: var(--red-600);
}

/* run drill-in */
.crumb {
	flex: none;
	display: flex;
	align-items: center;
	gap: 8px;
	padding: 12px 16px 0;
	font-size: 11.5px;
	color: var(--text-muted);
}
.crumb a {
	display: flex;
	align-items: center;
	gap: 5px;
	font-weight: 600;
	color: var(--primary);
}
.runhead {
	display: flex;
	align-items: baseline;
	gap: 10px;
	padding: 6px 16px 0;
	flex: none;
}
.runhead h2 {
	margin: 0;
	font-size: 17px;
	font-weight: 600;
	color: var(--text-color);
}
.item {
	display: grid;
	grid-template-columns: 112px 200px 1fr 56px;
	gap: 12px;
	align-items: center;
	padding: 8px 14px;
	border-top: 1px solid var(--control-bg);
	cursor: pointer;
}
.item:hover {
	background: var(--gray-50);
}
.item.bad {
	background: oklch(0.988 0.006 25);
}
.item-doc {
	font-size: 11.5px;
	color: var(--text-color);
	overflow: hidden;
	text-overflow: ellipsis;
	white-space: nowrap;
}
.item-doc em {
	font-style: normal;
	color: var(--text-light);
}
.item-msg {
	font-size: 11.5px;
	color: var(--text-muted);
	overflow: hidden;
	text-overflow: ellipsis;
	white-space: nowrap;
}
.item-msg.bad {
	color: var(--red-600);
}
.item-ms {
	font-size: 10.5px;
	color: var(--text-light);
	text-align: right;
	font-variant-numeric: tabular-nums;
	font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}

/* detail */
.detail {
	border-left: 1px solid var(--border-color);
	background: var(--fg-color);
	display: flex;
	flex-direction: column;
	min-height: 0;
}
.detail-head {
	padding: 14px 16px;
	border-bottom: 1px solid var(--border-color);
	flex: none;
}
.pair {
	display: flex;
	align-items: center;
	gap: 8px;
	min-width: 0;
}
.pair strong {
	font-size: 13.5px;
	font-weight: 600;
}
.realm {
	margin-top: 6px;
	font-size: 10.5px;
	color: var(--text-muted);
	font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
	overflow: hidden;
	text-overflow: ellipsis;
	white-space: nowrap;
}
.detail-scroll {
	flex: 1;
	overflow: auto;
	padding: 4px 16px 16px;
}
.meter {
	margin-bottom: 10px;
}
.meter-head {
	display: flex;
	align-items: baseline;
	gap: 8px;
	margin-bottom: 5px;
	font-size: 12px;
	color: var(--text-color);
}
.meter-head span {
	flex: 1;
}
.meter-head strong {
	font-size: 11.5px;
	font-weight: 600;
}
.meter-head strong.bad {
	color: var(--red-600);
}
.track {
	height: 4px;
	border-radius: 999px;
	background: var(--control-bg);
	overflow: hidden;
}
.fill {
	height: 4px;
	border-radius: 999px;
}
.fact {
	display: flex;
	align-items: baseline;
	gap: 8px;
	padding: 5px 0;
	font-size: 12px;
}
.fact span {
	flex: 1;
	color: var(--text-muted);
}
.fact strong {
	font-weight: 400;
	color: var(--text-color);
}
.error {
	margin: 12px 0 0;
	padding: 10px 12px;
	background: oklch(0.96 0.03 25);
	border-radius: 8px;
	font-size: 11px;
	line-height: 1.5;
	color: oklch(0.4 0.14 25);
	font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
	word-break: break-word;
}
.pair-buttons {
	display: flex;
	gap: 8px;
	margin-top: 12px;
}
.coverage {
	margin: 0 0 8px;
	font-size: 12px;
	color: var(--text-muted);
	text-wrap: pretty;
}
.failing {
	display: flex;
	align-items: center;
	gap: 8px;
	padding: 8px 10px;
	margin-bottom: 6px;
	border: 1px solid oklch(0.88 0.06 25);
	border-radius: 8px;
	font-size: 11.5px;
	cursor: pointer;
}
.failing span {
	flex: 1;
}
.failing b {
	font-weight: 600;
	color: var(--red-600);
	font-variant-numeric: tabular-nums;
}
.flag {
	display: flex;
	align-items: center;
	gap: 8px;
	padding: 6px 0;
	font-size: 12px;
}
.flag span {
	flex: 1;
	color: var(--text-color);
}
.flag span.muted {
	color: var(--text-light);
}
.flag em {
	font-style: normal;
	font-size: 11.5px;
	color: var(--text-muted);
}
.summary-line {
	display: flex;
	align-items: baseline;
	gap: 8px;
	padding: 4px 0;
	font-size: 12px;
}
.summary-line span {
	flex: 1;
	color: var(--text-muted);
}
.summary-line b {
	font-weight: 600;
	font-variant-numeric: tabular-nums;
}
.summary-line b.good {
	color: var(--green-600);
}
.summary-line b.bad {
	color: var(--red-600);
}
.summary-line b.warn {
	color: var(--yellow-600);
}
.rec {
	padding: 10px 0;
	border-top: 1px solid var(--control-bg);
}
.rec:first-of-type {
	border-top: 0;
}
.rec-head {
	display: flex;
	align-items: center;
	gap: 8px;
	margin-bottom: 3px;
}
.rec-head strong {
	flex: 1;
	font-size: 12px;
	font-weight: 600;
}
.rec p {
	margin: 0 0 8px;
	font-size: 11.5px;
	line-height: 1.5;
	color: var(--text-muted);
	text-wrap: pretty;
}
.rec p.rec-do {
	color: var(--text-color);
}
.rec .pair-buttons {
	margin-top: 0;
}
</style>

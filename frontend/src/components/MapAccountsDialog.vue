<template>
	<div class="xmap-backdrop" @click.self="$emit('close')">
		<div class="xmap" role="dialog" :aria-label="__('Map Xero account codes')">
			<div class="xmap-head">
				<h3>{{ __("Map Xero account codes") }}</h3>
				<p v-if="!loading && codes.length">
					{{ countSentence }}
					{{ __("Each one is a line ERPNext silently dropped — the document still posted, just short.") }}
				</p>
				<p v-else-if="!loading">{{ __("Nothing to map.") }}</p>
				<p v-else>{{ __("Reading the Xero chart of accounts…") }}</p>
			</div>

			<div v-if="loading" class="xmap-state">
				<Spin />
				{{ __("Fetching accounts from Xero") }}
			</div>

			<div v-else-if="error" class="xmap-state bad">{{ error }}</div>

			<div v-else-if="!codes.length" class="xmap-state">
				{{ __("Every Xero account code seen in the last seven days already has a mapping.") }}
			</div>

			<div v-else class="xmap-body">
				<div class="xmap-list">
					<div
						v-for="(c, i) in codes"
						:key="c.xero_code"
						class="code"
						:class="{ on: i === index, done: !!chosen[c.xero_code] }"
						@click="index = i"
					>
						<div class="code-num">{{ c.xero_code }}</div>
						<div class="code-name">{{ c.xero_name }}</div>
						<div class="code-err">
							<svg v-if="chosen[c.xero_code]" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="var(--green-600)" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5" /></svg>
							<template v-else>{{ c.error_count }}</template>
						</div>
						<div class="code-type">{{ c.xero_type }}</div>
					</div>
				</div>

				<div class="xmap-detail" v-if="current">
					<div class="xmap-card">
						<div class="code-num big">{{ current.xero_code }}</div>
						<div>
							<strong>{{ current.xero_name }}</strong>
							<small>
								{{ current.xero_type }} &middot; {{ current.error_count }}
								{{ current.error_count === 1 ? __("line dropped") : __("lines dropped") }}
							</small>
						</div>
					</div>

					<h6>{{ __("Suggested ERPNext accounts") }}</h6>

					<div
						v-for="s in (current.suggested_accounts || {}).suggestions || []"
						:key="s.account_name"
						class="sugg"
						:class="{ on: pick === s.account_name }"
						@click="choose(s.account_name)"
					>
						<div class="radio"></div>
						<div class="sugg-text">
							<strong>{{ s.account_name }}</strong>
							<span>
								{{ s.account_type || __("Account") }}
								<template v-if="s.parent_account"> &middot; {{ __("under") }} {{ s.parent_account }}</template>
							</span>
						</div>
						<!-- The raw score means nothing to a bookkeeper; the reason does. -->
						<span class="why" :class="reasonTone(s.match_score)">{{ reason(s.match_score) }}</span>
					</div>

					<p v-if="!((current.suggested_accounts || {}).suggestions || []).length" class="otherwise">
						{{ __("No ERPNext account of a matching type. Search the full chart below.") }}
					</p>
					<p v-else class="otherwise">{{ __("None of these? Search the full chart of accounts.") }}</p>
					<div ref="linkHost" class="field-host"></div>
				</div>
			</div>

			<div class="xmap-foot" v-if="!loading && codes.length">
				<label class="retry">
					<input type="checkbox" v-model="autoRetry" />
					<span class="box" :class="{ on: autoRetry }">
						<svg v-if="autoRetry" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5" /></svg>
					</span>
					{{ __("Re-sync the affected documents once every code is mapped") }}
				</label>
				<div class="spacer"></div>
				<span class="muted">{{ index + 1 }} {{ __("of") }} {{ codes.length }}</span>
				<button class="tbtn" @click="skip">{{ __("Skip") }}</button>
				<button class="tbtn primary" :disabled="saving || !pick" @click="next">
					<Spin v-if="saving" />
					{{ lastOne ? __("Map and finish") : __("Map and next") }}
				</button>
			</div>
			<div class="xmap-foot" v-else-if="!loading">
				<div class="spacer"></div>
				<button class="tbtn" @click="$emit('close')">{{ __("Close") }}</button>
			</div>
		</div>
	</div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch, nextTick } from "vue";
import Spin from "./Spin.vue";

const emit = defineEmits(["close", "mapped"]);
const API = "xero.xero.page.xero_sync_dashboard.xero_sync_dashboard.";

const loading = ref(true);
const saving = ref(false);
const error = ref("");
const codes = ref([]);
const index = ref(0);
const chosen = ref({});
const autoRetry = ref(true);
const linkHost = ref(null);
let linkControl = null;

const current = computed(() => codes.value[index.value] || null);
const lastOne = computed(() => index.value >= codes.value.length - 1);
const pick = computed(() => (current.value ? chosen.value[current.value.xero_code] || "" : ""));

const countSentence = computed(() => {
	const words = ["One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine"];
	const n = codes.value.length;
	const word = n <= words.length ? words[n - 1] : String(n);
	return `${word} ${n === 1 ? __("code") : __("codes")} ${__("turned up in errors over the last seven days.")}`;
});

// _score_account_suggestions() adds +100 for an exact account number, +50 for an
// exact name, +30 partial, +20 code-in-name, +10 per keyword, +5 same type.
function reason(score) {
	const s = Number(score) || 0;
	if (s >= 100) return __("Account number matches");
	if (s >= 50) return __("Name matches");
	if (s >= 30) return __("Similar name");
	if (s >= 20) return __("Code appears in name");
	return __("Same type only");
}
const reasonTone = (score) => ((Number(score) || 0) >= 50 ? "strong" : "weak");

function choose(account) {
	if (!current.value) return;
	chosen.value = { ...chosen.value, [current.value.xero_code]: account };
	if (linkControl) linkControl.set_value("");
}

function skip() {
	if (current.value) {
		const rest = { ...chosen.value };
		delete rest[current.value.xero_code];
		chosen.value = rest;
	}
	if (lastOne.value) finish();
	else index.value += 1;
}

async function next() {
	if (lastOne.value) await finish();
	else index.value += 1;
}

async function finish() {
	const mappings = codes.value
		.filter((c) => chosen.value[c.xero_code])
		.map((c) => ({
			xero_code: c.xero_code,
			xero_name: c.xero_name,
			erpnext_account: chosen.value[c.xero_code],
		}));

	if (!mappings.length) {
		emit("close");
		return;
	}

	saving.value = true;
	try {
		const result = await frappe.xcall(
			"xero.xero.doctype.xero_settings.xero_settings.quick_map_accounts",
			{ mappings: JSON.stringify(mappings), auto_retry: autoRetry.value ? 1 : 0 }
		);
		emit("mapped", { mapped: mappings.length, result });
	} catch (e) {
		saving.value = false;
	}
}

/* The full-chart fallback is a real Frappe Link control, so it gets the same
   search, permissions and awesomplete behaviour as anywhere else in Desk. */
function mountLink() {
	if (!linkHost.value) return;
	if (linkControl) {
		linkControl.set_value("");
		return;
	}
	linkControl = frappe.ui.form.make_control({
		df: {
			fieldtype: "Link",
			options: "Account",
			label: __("Account"),
			placeholder: __("Search the chart of accounts"),
			only_select: 1,
			get_query: () => ({ filters: { is_group: 0, disabled: 0 } }),
			change() {
				const value = linkControl.get_value();
				if (value) choose(value);
			},
		},
		parent: linkHost.value,
		render_input: true,
	});
	linkControl.$wrapper.find(".control-label").hide();
}

watch(
	current,
	(code) => {
		if (code && !chosen.value[code.xero_code]) {
			const top = ((code.suggested_accounts || {}).suggestions || [])[0];
			if (top && (Number(top.match_score) || 0) >= 50) {
				chosen.value = { ...chosen.value, [code.xero_code]: top.account_name };
			}
		}
		nextTick(mountLink);
	},
	{ immediate: true }
);

function onKey(e) {
	if (e.key === "Escape") emit("close");
}

onMounted(async () => {
	document.addEventListener("keydown", onKey);
	try {
		// This one does hit Xero — it decorates each code with the live chart —
		// so it is deliberately not part of the dashboard's first paint.
		const r = await frappe.xcall(API + "get_unmapped_accounts_from_errors", { days: 7 });
		if (r && r.success === false) error.value = r.error || __("Could not read the Xero chart of accounts.");
		codes.value = (r && r.unmapped_accounts) || [];
	} catch (e) {
		error.value = __("Could not reach Xero. Check the connection and try again.");
	}
	loading.value = false;
	nextTick(mountLink);
});

onUnmounted(() => document.removeEventListener("keydown", onKey));
</script>

<style scoped>
/* Named away from .modal / .modal-backdrop — Frappe ships Bootstrap and those
   two classes collide with it. */
.xmap-backdrop {
	position: fixed;
	inset: 0;
	z-index: 1055;
	display: flex;
	align-items: center;
	justify-content: center;
	background: rgba(23, 23, 23, 0.32);
}
.xmap {
	width: 760px;
	max-width: calc(100vw - 40px);
	min-height: 440px;
	max-height: calc(100vh - 80px);
	display: flex;
	flex-direction: column;
	background: var(--card-bg);
	border-radius: 12px;
	overflow: hidden;
	box-shadow: 0 18px 48px rgba(23, 23, 23, 0.22);
}
.xmap-head {
	flex: none;
	padding: 16px 18px 12px;
	border-bottom: 1px solid var(--border-color);
}
.xmap-head h3 {
	margin: 0 0 4px;
	font-size: 15.5px;
	font-weight: 600;
	color: var(--text-color);
}
.xmap-head p {
	margin: 0;
	font-size: 11.5px;
	color: var(--text-muted);
	text-wrap: pretty;
	max-width: 560px;
}
.xmap-state {
	flex: 1;
	display: flex;
	align-items: center;
	justify-content: center;
	gap: 8px;
	font-size: 12.5px;
	color: var(--text-muted);
	padding: 20px;
	text-align: center;
	text-wrap: pretty;
}
.xmap-state.bad {
	color: var(--red-600);
}
.xmap-body {
	flex: 1 1 auto;
	display: grid;
	grid-template-columns: 244px 1fr;
	min-height: 0;
}
.xmap-list {
	border-right: 1px solid var(--border-color);
	overflow: auto;
	padding: 8px;
}
.code {
	display: grid;
	grid-template-columns: 42px 1fr auto;
	gap: 2px 8px;
	padding: 8px;
	margin: 1px 0;
	border-radius: 8px;
	cursor: pointer;
}
.code:hover,
.code.on {
	background: var(--control-bg);
}
.code-num {
	grid-row: span 2;
	font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
	font-size: 12.5px;
	font-weight: 600;
	color: var(--text-color);
	align-self: center;
}
.code-name {
	font-size: 12px;
	color: var(--text-color);
	overflow: hidden;
	text-overflow: ellipsis;
	white-space: nowrap;
}
.code.on .code-name {
	font-weight: 600;
}
.code.done .code-name {
	color: var(--text-light);
}
.code-type {
	font-size: 10px;
	letter-spacing: 0.03em;
	color: var(--text-light);
}
.code-err {
	font-size: 10.5px;
	font-weight: 600;
	color: var(--red-600);
	align-self: center;
	font-variant-numeric: tabular-nums;
	display: flex;
	align-items: center;
}
.xmap-detail {
	overflow: auto;
	padding: 16px 18px;
}
.xmap-card {
	display: flex;
	align-items: center;
	gap: 10px;
	padding: 11px 13px;
	background: var(--control-bg);
	border-radius: 9px;
	margin-bottom: 16px;
}
.code-num.big {
	grid-row: auto;
	flex: none;
	font-size: 15px;
}
.xmap-card > div:last-child {
	flex: 1;
	min-width: 0;
}
.xmap-card strong {
	display: block;
	font-size: 13px;
	font-weight: 600;
}
.xmap-card small {
	display: block;
	margin-top: 1px;
	font-size: 10.5px;
	color: var(--text-muted);
	letter-spacing: 0.03em;
}
h6 {
	margin: 0 0 8px;
	font-size: 10.5px;
	font-weight: 700;
	letter-spacing: 0.05em;
	text-transform: uppercase;
	color: var(--text-muted);
}
.sugg {
	display: flex;
	align-items: center;
	gap: 11px;
	padding: 11px 13px;
	margin-bottom: 7px;
	border: 1px solid var(--border-color);
	border-radius: 9px;
	cursor: pointer;
	background: var(--card-bg);
}
.sugg:hover {
	border-color: var(--gray-400);
}
.sugg.on {
	border-color: var(--primary);
	box-shadow: inset 0 0 0 1px var(--primary);
}
.radio {
	width: 15px;
	height: 15px;
	border-radius: 999px;
	border: 1.5px solid var(--gray-400);
	flex: none;
}
.sugg.on .radio {
	border-color: var(--primary);
	border-width: 4.5px;
}
.sugg-text {
	flex: 1;
	min-width: 0;
}
.sugg-text strong {
	display: block;
	font-size: 12.5px;
	font-weight: 500;
	color: var(--text-color);
}
.sugg-text span {
	display: block;
	margin-top: 2px;
	font-size: 11px;
	color: var(--text-muted);
}
.why {
	font-size: 10.5px;
	font-weight: 600;
	padding: 2px 8px;
	border-radius: 999px;
	flex: none;
}
.why.strong {
	background: var(--green-100);
	color: var(--green-600);
}
.why.weak {
	background: var(--control-bg);
	color: var(--text-light);
}
.otherwise {
	margin: 14px 0 6px;
	font-size: 11.5px;
	color: var(--text-muted);
}
.field-host :deep(.frappe-control) {
	margin-bottom: 0;
}
.xmap-foot {
	flex: none;
	display: flex;
	align-items: center;
	gap: 8px;
	padding: 12px 18px;
	border-top: 1px solid var(--border-color);
	background: var(--fg-color);
}
.spacer {
	flex: 1;
}
.muted {
	font-size: 11.5px;
	color: var(--text-muted);
}
.retry {
	display: flex;
	align-items: center;
	gap: 8px;
	margin: 0;
	font-size: 11.5px;
	font-weight: 400;
	color: var(--text-color);
	cursor: pointer;
}
.retry input {
	position: absolute;
	opacity: 0;
	pointer-events: none;
}
.retry .box {
	width: 15px;
	height: 15px;
	border-radius: 4px;
	border: 1.5px solid var(--gray-400);
	background: var(--card-bg);
	display: flex;
	align-items: center;
	justify-content: center;
	flex: none;
}
.retry .box.on {
	background: var(--primary);
	border-color: var(--primary);
}
.tbtn {
	display: flex;
	align-items: center;
	gap: 6px;
	height: 32px;
	padding: 0 12px;
	border-radius: 7px;
	border: 1px solid var(--border-color);
	font-size: 12.5px;
	font-weight: 600;
	color: var(--text-color);
	background: var(--card-bg);
	cursor: pointer;
	font-family: inherit;
	white-space: nowrap;
}
.tbtn:hover {
	background: var(--control-bg);
}
.tbtn.primary {
	background: var(--primary);
	border-color: var(--primary);
	color: white;
}
.tbtn.primary:hover {
	opacity: 0.9;
}
.tbtn[disabled] {
	opacity: 0.35;
	pointer-events: none;
}
</style>

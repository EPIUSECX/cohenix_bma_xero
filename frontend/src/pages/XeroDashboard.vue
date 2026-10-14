<template>
	<div ref="root" class="flex w-full overflow-hidden bg-surface-base text-ink-gray-8" :style="{ height: height + 'px' }">
		<!-- ===================== main ===================== -->
		<main class="flex min-w-0 flex-1 flex-col">
			<!-- --- run drill-in --- -->
			<template v-if="selectedRun">
				<header class="flex h-[45px] shrink-0 items-center gap-3 border-b border-outline-gray-1 px-5">
					<Button variant="ghost" icon-left="lucide-arrow-left" :label="__('Activity')" @click="selectedRun = null" />
					<span class="h-4 w-px bg-outline-gray-2" />
					<h2 class="min-w-0 truncate text-lg font-medium text-ink-gray-9">{{ runTitle(selectedRun) }}</h2>
					<Badge :theme="statusTheme(selectedRun.overall_status)" :label="statusLabel(selectedRun.overall_status)" />
					<span class="ml-auto shrink-0 text-p-sm text-ink-gray-5">
						{{ ago(selectedRun.sync_time) }}
						<template v-if="selectedRun.duration"> · {{ secs(selectedRun.duration) }}</template>
						<template v-if="selectedRun.sync_batch_id"> · {{ __("batch") }} {{ shortId(selectedRun.sync_batch_id, 6) }}</template>
					</span>
				</header>

				<div class="flex h-12 shrink-0 items-center gap-2 px-5">
					<h3 class="text-lg font-medium text-ink-gray-9">{{ __("Items") }}</h3>
					<span class="text-sm text-ink-gray-5">{{ (selectedRun.items || []).length }}</span>
					<div class="ml-auto flex items-center gap-2">
						<Button
							v-if="runFailures(selectedRun).length"
							:variant="failuresOnly ? 'subtle' : 'outline'"
							:label="__('Failures only')"
							@click="failuresOnly = !failuresOnly"
						/>
						<Button
							v-if="runFailures(selectedRun).length"
							variant="solid"
							:loading="busy === 'retry'"
							:disabled="!!busy"
							:label="__('Retry') + ' ' + runFailures(selectedRun).length"
							@click="retryLogs(runFailures(selectedRun).map((i) => i.log_name))"
						/>
					</div>
				</div>

				<ScrollArea class="min-h-0 flex-1" viewport-class="pb-6 [&>div]:!block">
					<div v-if="!visibleItems.length" class="px-5 py-10 text-center text-p-sm text-ink-gray-4">
						{{ __("No items logged for this run.") }}
					</div>
					<List v-else :columns="['8rem', 'minmax(0,15rem)', 'minmax(0,1fr)', '5rem']" :row-height="44" class="list-row-px-5">
						<ListHeader>
							<ListHeaderCell>{{ __("Status") }}</ListHeaderCell>
							<ListHeaderCell>{{ __("Document") }}</ListHeaderCell>
							<ListHeaderCell>{{ __("Message") }}</ListHeaderCell>
							<ListHeaderCell class="justify-end">{{ __("Time") }}</ListHeaderCell>
						</ListHeader>
						<ListRows :items="visibleItems" row-key="log_name" v-slot="{ item }">
							<ListRow :value="item.log_name" @click="openLogDoc(item.log_name)">
								<ListCell><Badge :theme="statusTheme(item.status)" :label="statusLabel(item.status)" /></ListCell>
								<ListCell class="truncate text-ink-gray-9">
									{{ item.erpnext_doc_name }}
									<span v-if="item.erpnext_doc_type" class="ml-1 text-ink-gray-5">· {{ __(item.erpnext_doc_type) }}</span>
								</ListCell>
								<ListCell class="truncate" :class="item.status === 'Error' ? 'text-ink-red-6' : 'text-ink-gray-6'" :title="item.message">{{ item.message }}</ListCell>
								<ListCell class="justify-end tabular-nums text-ink-gray-5">{{ ms(item.processing_time) }}</ListCell>
							</ListRow>
						</ListRows>
					</List>
				</ScrollArea>
			</template>

			<!-- --- tabs --- -->
			<template v-else>
				<Alert
					v-if="banner"
					class="m-3 shrink-0"
					:theme="banner.tone === 'bad' ? 'red' : 'amber'"
					:title="banner.title"
					:description="banner.text"
				>
					<template #actions>
						<Button size="sm" variant="outline" :loading="busy === 'reconnect'" :disabled="!!busy" :label="banner.label" @click="banner.act" />
					</template>
				</Alert>

				<Tabs
					v-model="activeTab"
					:tabs="tabs"
					class="flex min-h-0 flex-1 flex-col [&_[role='tab']]:shrink-0 [&_[role='tab']]:px-1 [&_[role='tablist']]:min-h-[45px] [&_[role='tablist']]:gap-[22px] [&_[role='tablist']]:px-5 [&>[role='tabpanel']:not([hidden])]:flex [&>[role='tabpanel']:not([hidden])]:min-h-0 [&>[role='tabpanel']:not([hidden])]:grow [&>[role='tabpanel']]:flex-col [&>[role='tabpanel']]:overflow-auto"
				>
					<template #tab-suffix="{ tab }">
						<Badge v-if="tab.data && tab.data.count" :theme="tab.data.theme || 'gray'" :label="String(tab.data.count)" />
					</template>

					<template #tab-panel="{ tab }">
						<!-- Needs attention -->
						<ScrollArea v-if="tab.value === 'attention'" class="min-h-0 flex-1" viewport-class="pb-6 [&>div]:!block">
							<div v-if="loading" class="px-5 py-10 text-center text-p-sm text-ink-gray-4">{{ __("Checking…") }}</div>
							<div v-else-if="!attention.length" class="flex flex-col items-center gap-2 px-5 py-16 text-center">
								<span class="lucide-circle-check size-8 text-ink-green-6" aria-hidden="true" />
								<div class="text-base font-medium text-ink-gray-9">
									{{ connected ? __("Nothing needs attention") : __("Nothing to report yet") }}
								</div>
								<div class="max-w-sm text-p-sm text-ink-gray-5">
									<template v-if="!connected">{{ __("Connect Xero and any sync problems will be listed here.") }}</template>
									<template v-else-if="coverage.synced">{{ coverage.synced.toLocaleString() }} {{ __("records all carry a Xero ID.") }}</template>
								</div>
							</div>
							<div
								v-for="(a, i) in attention"
								:key="a.key"
								class="flex items-center gap-3 border-b border-outline-gray-1 px-5 py-3"
							>
								<span class="size-2 shrink-0 rounded-full" :class="severityDot(a.severity)" :title="__(a.severity)" />
								<div class="min-w-0 flex-1">
									<div class="flex items-center gap-2">
										<span class="truncate text-base font-medium text-ink-gray-9">{{ a.title }}</span>
										<Badge :label="String(a.count)" />
									</div>
									<div class="line-clamp-2 text-p-sm text-ink-gray-6" :title="a.detail">{{ a.detail }}</div>
								</div>
								<Button
									class="shrink-0"
									:variant="i === 0 || a.action.primary ? 'solid' : 'subtle'"
									:loading="busy === a.key"
									:disabled="!!busy"
									:label="a.action.label"
									@click="runAction(a.action)"
								/>
							</div>
						</ScrollArea>

						<!-- Activity -->
						<template v-else-if="tab.value === 'activity'">
							<div class="flex h-12 shrink-0 items-center gap-2 px-5">
								<h3 class="text-lg font-medium text-ink-gray-9">{{ __("Sync activity") }}</h3>
								<span class="text-sm text-ink-gray-5">{{ __("last 7 days") }}</span>
								<Button class="ml-auto" variant="outline" iconRight="lucide-arrow-up-right" :label="__('All runs')" @click="openLogs()" />
							</div>
							<ScrollArea class="min-h-0 flex-1" viewport-class="pb-6 [&>div]:!block">
								<div v-if="loading" class="px-5 py-10 text-center text-p-sm text-ink-gray-4">{{ __("Loading…") }}</div>
								<div v-else-if="!runs.length" class="px-5 py-16 text-center text-p-sm text-ink-gray-4">
									{{ __("No sync has run in the last seven days.") }}
								</div>
								<List v-else :columns="['4.5rem', '7rem', 'minmax(7rem,1fr)', '14rem', '7rem']" :row-height="44" class="list-row-px-5">
									<ListHeader>
										<ListHeaderCell>{{ __("Time") }}</ListHeaderCell>
										<ListHeaderCell>{{ __("Direction") }}</ListHeaderCell>
										<ListHeaderCell>{{ __("Entities") }}</ListHeaderCell>
										<ListHeaderCell>{{ __("Results") }}</ListHeaderCell>
										<ListHeaderCell class="justify-end">{{ __("Status") }}</ListHeaderCell>
									</ListHeader>
									<ListGroup v-for="g in runGroups" :key="g.label" :label="g.label">
										<ListRows :items="g.items" :row-key="runKey" v-slot="{ item: run }">
											<ListRow :value="runKey(run)" @click="openRun(run)">
												<ListCell class="tabular-nums text-ink-gray-6" :title="ago(run.sync_time)">{{ clock(run.sync_time) }}</ListCell>
												<ListCell class="gap-1.5 text-ink-gray-7">
													<span :class="inbound(run) ? 'lucide-arrow-down-left' : 'lucide-arrow-up-right'" class="size-3.5 text-ink-gray-5" aria-hidden="true" />
													{{ inbound(run) ? __("From Xero") : __("To Xero") }}
												</ListCell>
												<ListCell class="truncate text-ink-gray-9" :title="(run.entities_synced || []).join(', ')">{{ (run.entities_synced || []).join(", ") || __("Unknown") }}</ListCell>
												<ListCell class="gap-1.5">
													<span class="tabular-nums text-ink-gray-7">{{ run.success_count || 0 }} {{ __("ok") }}</span>
													<Badge v-if="run.error_count" theme="red" :label="run.error_count + ' ' + __('failed')" />
													<Badge v-if="run.warning_count" theme="amber" :label="run.warning_count + ' ' + (run.warning_count === 1 ? __('warning') : __('warnings'))" />
												</ListCell>
												<ListCell class="justify-end"><Badge :theme="statusTheme(run.overall_status)" :label="statusLabel(run.overall_status)" /></ListCell>
											</ListRow>
										</ListRows>
									</ListGroup>
								</List>
							</ScrollArea>
						</template>

						<!-- Entities -->
						<ScrollArea v-else-if="tab.value === 'entities'" class="min-h-0 flex-1" viewport-class="pb-6 [&>div]:!block">
							<List :columns="['minmax(9rem,1fr)', '6rem', '6rem', '13rem', '7rem']" :row-height="44" class="list-row-px-5">
								<ListHeader>
									<ListHeaderCell>{{ __("Entity") }}</ListHeaderCell>
									<ListHeaderCell class="justify-end">{{ __("Synced") }}</ListHeaderCell>
									<ListHeaderCell class="justify-end">{{ __("Total") }}</ListHeaderCell>
									<ListHeaderCell>{{ __("Coverage") }}</ListHeaderCell>
									<ListHeaderCell class="justify-end">{{ __("Failing") }}</ListHeaderCell>
								</ListHeader>
								<ListGroup v-for="g in entityGroups" :key="g.label" :label="g.label">
									<ListRows :items="g.items" row-key="entity" v-slot="{ item: e }">
										<ListRow :value="e.entity" @click="pickEntity(e)">
											<ListCell class="truncate text-ink-gray-9">{{ __(e.entity) }}</ListCell>
											<ListCell class="justify-end tabular-nums text-ink-gray-7">{{ e.synced.toLocaleString() }}</ListCell>
											<ListCell class="justify-end tabular-nums text-ink-gray-7">{{ e.total.toLocaleString() }}</ListCell>
											<ListCell class="gap-2">
												<Meter class="w-24" :value="e.sync_rate" :color="e.errors ? red : green" />
												<span class="w-10 text-right text-sm tabular-nums text-ink-gray-6">{{ Math.round(e.sync_rate) }}%</span>
											</ListCell>
											<ListCell class="justify-end">
												<Badge v-if="e.errors" theme="red" :label="String(e.errors)" />
												<span v-else class="text-ink-gray-4">—</span>
											</ListCell>
										</ListRow>
									</ListRows>
								</ListGroup>
							</List>
						</ScrollArea>
					</template>
				</Tabs>
			</template>
		</main>

		<!-- ===================== side panel ===================== -->
		<aside class="flex w-[22rem] shrink-0 flex-col border-l border-outline-gray-1">
			<!-- run detail -->
			<template v-if="selectedRun">
				<div class="flex h-[45px] shrink-0 items-center gap-2 border-b border-outline-gray-1 px-5 text-lg font-medium text-ink-gray-9">
					{{ __("This run") }}
					<Badge v-if="selectedRun.error_count" theme="red" :label="selectedRun.error_count + ' ' + __('failed')" />
					<Badge v-else theme="green" :label="__('Clean')" />
				</div>
				<ScrollArea class="min-h-0 flex-1" viewport-class="[&>div]:!block">
					<CollapsibleSection :label="__('Outcome')">
						<FieldRow :label="__('Succeeded')"><span class="tabular-nums text-ink-green-6">{{ selectedRun.success_count || 0 }}</span></FieldRow>
						<FieldRow :label="__('Failed')"><span class="tabular-nums" :class="selectedRun.error_count ? 'text-ink-red-6' : ''">{{ selectedRun.error_count || 0 }}</span></FieldRow>
						<FieldRow :label="__('Warnings')"><span class="tabular-nums" :class="selectedRun.warning_count ? 'text-ink-amber-7' : ''">{{ selectedRun.warning_count || 0 }}</span></FieldRow>
						<FieldRow v-if="selectedRun.skipped_count" :label="__('Skipped')"><span class="tabular-nums">{{ selectedRun.skipped_count }}</span></FieldRow>
						<FieldRow v-if="selectedRun.duration" :label="__('Duration')"><span class="tabular-nums">{{ secs(selectedRun.duration) }}</span></FieldRow>
					</CollapsibleSection>

					<template v-if="(selectedRun.failure_summary || []).length">
						<div class="h-px border-t border-outline-gray-1" />
						<CollapsibleSection :label="__('Why it failed')">
							<FieldRow v-for="f in selectedRun.failure_summary" :key="f.failure_category" :label="__(f.failure_category)">
								<span class="tabular-nums">{{ f.count }}</span>
							</FieldRow>
						</CollapsibleSection>
					</template>

					<template v-if="(selectedRun.actionable_recommendations || []).length">
						<div class="h-px border-t border-outline-gray-1" />
						<CollapsibleSection :label="__('What to do')">
							<div v-for="(r, i) in selectedRun.actionable_recommendations" :key="i" class="mx-3 space-y-2 rounded-lg border border-outline-gray-1 p-3">
								<div class="flex items-start justify-between gap-2">
									<span class="text-base font-medium text-ink-gray-9">{{ r.title }}</span>
									<Badge :theme="severityTheme(r.severity)" :label="__(r.severity)" />
								</div>
								<p class="text-p-sm text-ink-gray-6">{{ r.message }}</p>
								<p v-if="r.action" class="text-p-sm text-ink-gray-8">{{ r.action }}</p>
								<div class="flex gap-2 pt-1">
									<Button v-if="r.action_button" class="flex-1" :variant="i === 0 ? 'solid' : 'outline'" :label="r.action_button.label" @click="goRoute(r.action_button.route)" />
									<Button v-if="r.secondary_button" class="flex-1" variant="outline" :label="r.secondary_button.label" @click="openLogs(r.secondary_button.filter)" />
								</div>
							</div>
						</CollapsibleSection>
					</template>
				</ScrollArea>
			</template>

			<!-- connection -->
			<template v-else>
				<Tooltip :text="conn.tenant_id ? __('Copy tenant ID') : ''">
					<button
						type="button"
						class="flex h-[45px] w-full shrink-0 items-center gap-2 border-b border-outline-gray-1 px-5 text-left text-lg font-medium text-ink-gray-9"
						@click="copyTenant"
					>
						<span class="truncate">{{ conn.tenant_id ? shortId(conn.tenant_id, 8) : __("No organisation") }}</span>
						<span v-if="conn.tenant_id" class="lucide-copy size-3.5 shrink-0 text-ink-gray-4" aria-hidden="true" />
					</button>
				</Tooltip>

				<div class="flex shrink-0 items-center gap-4 border-b border-outline-gray-1 p-5">
					<Avatar size="3xl" shape="square" :label="tenantName || 'Xero'" image="/assets/xero/images/xero-logo.svg" />
					<div class="flex min-w-0 flex-col gap-2.5">
						<div class="truncate text-2xl font-medium text-ink-gray-9" :title="tenantName">{{ tenantName || __("Not connected") }}</div>
						<div class="flex items-center gap-1.5">
							<Badge :theme="connected ? 'green' : 'red'" :label="connected ? __('Connected') : __('Not connected')" />
							<Button :tooltip="__('Test connection')" icon="lucide-plug-zap" :loading="busy === 'test'" :disabled="!connected || !!busy" @click="testConnection" />
							<Button :tooltip="__('Reconnect')" icon="lucide-refresh-cw" :loading="busy === 'reconnect'" :disabled="!!busy" @click="reconnect" />
							<Button :tooltip="__('Xero Settings')" icon="lucide-settings" @click="openSettings" />
						</div>
					</div>
				</div>

				<ScrollArea class="min-h-0 flex-1" viewport-class="[&>div]:!block">
					<CollapsibleSection :label="__('Authorisation')">
						<template v-if="accessLeft !== null || refreshLeft !== null">
							<FieldRow v-if="accessLeft !== null" :label="__('Access token')">
								<div class="space-y-1.5">
									<div class="tabular-nums" :class="accessLeft <= 0 ? 'text-ink-red-6' : ''">{{ accessLabel }}</div>
									<Meter :value="pct(accessLeft, 30)" :color="accessLeft <= 0 ? red : green" />
								</div>
							</FieldRow>
							<FieldRow v-if="refreshLeft !== null" :label="__('Refresh token')">
								<div class="space-y-1.5">
									<div class="tabular-nums" :class="refreshLeft <= 10 ? 'text-ink-red-6' : ''">{{ Math.max(refreshLeft, 0) }} {{ __("of 60 days") }}</div>
									<Meter :value="pct(refreshLeft, 60)" :color="refreshTint" />
								</div>
							</FieldRow>
						</template>
						<FieldRow v-else :label="__('Token')"><span class="text-ink-gray-5">{{ __("None on record") }}</span></FieldRow>
					</CollapsibleSection>

					<div class="h-px border-t border-outline-gray-1" />
					<CollapsibleSection :label="__('Last run')">
						<FieldRow :label="__('Finished')"><span class="tabular-nums">{{ ago(conn.last_sync || (lastRun && lastRun.sync_time)) }}</span></FieldRow>
						<FieldRow v-if="lastRun && lastRun.duration" :label="__('Duration')"><span class="tabular-nums">{{ secs(lastRun.duration) }}</span></FieldRow>
						<FieldRow v-if="health.status" :label="__('Health')">
							<Badge :theme="health.score >= 80 ? 'green' : health.score >= 50 ? 'amber' : 'red'" :label="__(health.status) + ' · ' + health.score" />
						</FieldRow>
						<FieldRow v-if="health.success_rate !== undefined" :label="__('Success rate')"><span class="tabular-nums">{{ health.success_rate }}%</span><span class="ml-1 text-sm text-ink-gray-5">24h</span></FieldRow>
						<FieldRow :label="__('Stuck jobs')"><span class="tabular-nums">{{ health.stuck_jobs || __("None") }}</span></FieldRow>
						<div v-if="topError" class="mx-3 mt-1 whitespace-pre-wrap break-words rounded-lg bg-surface-red-1 p-3 font-mono text-xs text-ink-red-6">{{ topError }}</div>
					</CollapsibleSection>

					<div class="h-px border-t border-outline-gray-1" />
					<CollapsibleSection :label="__('Direction')">
						<FieldRow :label="__('To Xero')">
							<div class="flex items-center gap-2">
								<span class="size-2 rounded-full" :class="conn.sync_to_xero_enabled ? 'bg-surface-green-3' : 'bg-surface-gray-4'" />
								<span :class="conn.sync_to_xero_enabled ? '' : 'text-ink-gray-5'">{{ conn.sync_to_xero_enabled ? scheduleLabel : __("Off") }}</span>
							</div>
						</FieldRow>
						<FieldRow :label="__('From Xero')">
							<div class="flex items-center gap-2">
								<span class="size-2 rounded-full" :class="conn.sync_from_xero_enabled ? 'bg-surface-green-3' : 'bg-surface-gray-4'" />
								<span :class="conn.sync_from_xero_enabled ? '' : 'text-ink-gray-5'">{{ conn.sync_from_xero_enabled ? scheduleLabel : __("Off") }}</span>
							</div>
						</FieldRow>
					</CollapsibleSection>

					<template v-if="coverage.total">
						<div class="h-px border-t border-outline-gray-1" />
						<CollapsibleSection :label="__('Coverage')">
							<FieldRow :label="__('Xero IDs')">
								<div class="space-y-1.5">
									<div class="tabular-nums">{{ coverage.synced.toLocaleString() }} <span class="text-ink-gray-5">/ {{ coverage.total.toLocaleString() }} · {{ coverage.pct }}%</span></div>
									<Meter :value="coverage.pct" :color="failing.length ? amber : green" />
								</div>
							</FieldRow>
							<FieldRow :label="__('Failing')">
								<span v-if="!failing.length" class="text-ink-gray-5">{{ __("None") }}</span>
								<div v-else class="flex flex-wrap gap-1">
									<button v-for="e in failing" :key="e.entity" type="button" @click="pickEntity(e)">
										<Badge theme="red" :label="__(e.entity) + ' · ' + e.errors" />
									</button>
								</div>
							</FieldRow>
						</CollapsibleSection>
					</template>
				</ScrollArea>
			</template>
		</aside>

		<Teleport to="body">
			<MapAccountsDialog v-if="mapOpen" @close="mapOpen = false" @mapped="onMapped" />
		</Teleport>
	</div>
</template>

<script setup>
// Xero Sync Dashboard: connection, entity health and recent runs, as a Frappe UI page mounted in the
// Desk page `xero-sync-dashboard`. Desk draws the page head, so its title indicator, primary action
// and Refresh button stand in for a toolbar of our own.
import { ref, computed, onMounted, onBeforeUnmount, watch } from "vue";
import { Alert, Avatar, Badge, Button, ScrollArea, Tabs, Tooltip } from "frappe-ui";
import { List, ListCell, ListGroup, ListHeader, ListHeaderCell, ListRow, ListRows } from "frappe-ui/list";
import CollapsibleSection from "../components/CollapsibleSection.vue";
import FieldRow from "../components/FieldRow.vue";
import MapAccountsDialog from "../components/MapAccountsDialog.vue";
import Meter from "../components/Meter.vue";

const props = defineProps({ page: { type: Object, default: null } });
const root = ref(null);
const height = ref(640);

// Fill the Desk page from where the dashboard starts to the bottom of the window.
function fit() {
	if (!root.value) return;
	const top = root.value.getBoundingClientRect().top;
	height.value = Math.max(480, Math.floor(window.innerHeight - top));
}

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
	if (!tabChosen) {
		tabChosen = true;
		activeTab.value = attention.value.length ? "attention" : "activity";
	}
}

onMounted(() => {
	load();
	timer = setInterval(() => {
		if (!busy.value && !document.hidden) load();
	}, 60000);
});
onBeforeUnmount(() => clearInterval(timer));

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
	// An entity can report more Xero IDs than records (deleted or merged documents); count at most
	// what exists so coverage never reads above 100%.
	const total = entities.value.reduce((n, e) => n + (e.total || 0), 0);
	const synced = entities.value.reduce((n, e) => n + Math.min(e.synced || 0, e.total || 0), 0);
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


const statusTheme = (status) => ({ fail: "red", partial: "amber", ok: "green" })[statusClass(status)];
const STATUS_LABEL = { "Success with Warnings": "Warnings", "Partial Success": "Partial" };
const statusLabel = (status) => __(STATUS_LABEL[status] || status);

// Records that carry money or a posting, then the masters they refer to.
const TRANSACTIONS = ["Sales Invoice", "Purchase Invoice", "Payment Entry", "Journal Entry", "Quotation", "Bank Transaction"];
const entityGroups = computed(() =>
	[
		{ label: __("Transactions"), items: entities.value.filter((e) => TRANSACTIONS.includes(e.entity)) },
		{ label: __("Masters"), items: entities.value.filter((e) => !TRANSACTIONS.includes(e.entity)) },
	].filter((g) => g.items.length)
);
const severityDot = (s) =>
	({ high: "bg-surface-red-5", critical: "bg-surface-red-5", medium: "bg-surface-amber-3", low: "bg-surface-gray-4" })[(s || "").toLowerCase()] ||
	"bg-surface-gray-4";
const severityTheme = (s) =>
	({ high: "red", critical: "red", error: "red", medium: "amber", warning: "amber", warn: "amber" })[(s || "").toLowerCase()] || "gray";


/* -------------------------------------------------------------------- tabs */

const activeTab = ref("activity");
let tabChosen = false;
const tabs = computed(() => [
	{ value: "attention", label: __("Needs attention"), iconLeft: "lucide-triangle-alert", data: { count: attention.value.length, theme: "red" } },
	{ value: "activity", label: __("Activity"), iconLeft: "lucide-activity", data: { count: 0 } },
	{ value: "entities", label: __("Entities"), iconLeft: "lucide-boxes", data: { count: 0 } },
]);

const parseTime = (v) => new Date(String(v).replace(" ", "T"));
const startOfDay = (d) => new Date(d.getFullYear(), d.getMonth(), d.getDate());
const clock = (v) => parseTime(v).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
function dayLabel(v) {
	const d = parseTime(v);
	const diff = Math.round((startOfDay(new Date()) - startOfDay(d)) / 86400000);
	if (diff <= 0) return __("Today");
	if (diff === 1) return __("Yesterday");
	return d.toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "short" });
}
// Runs arrive newest first; keep that order within each day.
const runGroups = computed(() => {
	const days = new Map();
	for (const run of runs.value) {
		const key = dayLabel(run.sync_time);
		if (!days.has(key)) days.set(key, []);
		days.get(key).push(run);
	}
	return [...days].map(([label, items]) => ({ label, items }));
});

function copyTenant() {
	if (!conn.value.tenant_id) return;
	frappe.utils.copy_to_clipboard(conn.value.tenant_id);
}

/* ----------------------------------------------------------- Desk page head */

function syncHead() {
	const page = props.page;
	if (!page) return;
	const colour = !connected.value ? "red" : attention.value.length ? "orange" : "green";
	page.set_indicator(overallLabel.value, loading.value && !entities.value.length ? "gray" : colour);
	page.btn_primary?.prop("disabled", !connected.value || !!busy.value);
}
watch([connected, busy, loading, attention], syncHead);

onMounted(() => {
	fit();
	window.addEventListener("resize", fit);
	props.page?.set_primary_action(__("Sync all"), () => syncAll());
	props.page?.set_secondary_action(__("Refresh"), () => load());
	syncHead();
});
onBeforeUnmount(() => {
	window.removeEventListener("resize", fit);
	props.page?.clear_primary_action?.();
	props.page?.clear_secondary_action?.();
	props.page?.clear_indicator?.();
});

defineExpose({ load, syncAll, openLogs });
</script>

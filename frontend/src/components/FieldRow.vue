<template>
	<div class="flex min-h-7 items-center gap-2 px-3 leading-5">
		<div class="w-[38%] min-w-20 shrink-0 truncate text-sm text-ink-gray-5" :title="label">{{ label }}</div>
		<div class="min-w-0 flex-1 text-base text-ink-gray-9"><slot /></div>
	</div>
</template>

<script setup>
defineProps({ label: { type: String, required: true } });
</script>

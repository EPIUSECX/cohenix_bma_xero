<template>
	<div class="h-1.5 overflow-hidden rounded-full bg-surface-gray-2">
		<div class="h-full rounded-full transition-all" :style="{ width: Math.max(0, Math.min(100, value)) + '%', background: color }" />
	</div>
</template>

<script setup>
defineProps({ value: { type: Number, default: 0 }, color: { type: String, default: "var(--green-500)" } });
</script>

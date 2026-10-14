<template>
	<section class="p-1 sm:p-3">
		<button
			type="button"
			class="flex h-8 w-full items-center gap-2 px-2 text-left text-base font-semibold text-ink-gray-9"
			@click="opened = !opened"
		>
			<span class="lucide-chevron-right size-4 transition-transform duration-200" :class="{ 'rotate-90': opened }" aria-hidden="true" />
			<span>{{ label }}</span>
			<span class="ml-auto"><slot name="actions" /></span>
		</button>
		<div v-show="opened" class="flex flex-col gap-1.5 pb-1">
			<slot />
		</div>
	</section>
</template>

<script setup>
import { ref } from "vue";

const props = defineProps({
	label: { type: String, required: true },
	open: { type: Boolean, default: true },
});
const opened = ref(props.open);
</script>

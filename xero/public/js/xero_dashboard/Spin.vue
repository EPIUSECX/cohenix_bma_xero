<template>
	<svg class="spin" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round">
		<path d="M21 12a9 9 0 1 1-6.2-8.6" />
	</svg>
</template>

<style scoped>
.spin {
	animation: spin 0.7s linear infinite;
	flex: none;
}
@keyframes spin {
	to {
		transform: rotate(360deg);
	}
}
</style>

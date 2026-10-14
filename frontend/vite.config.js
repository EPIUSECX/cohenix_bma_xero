// Xero Desk pages as one ES module that each Desk page imports at runtime (be_pages.bundle.js).
//
// Library mode, not an app: there is no index.html and no router. The bundle carries its own
// Vue 3.5 because Frappe UI 1.0 needs it and Desk 16.50 ships Vue 3.3; the two never share
// components, so they do not conflict. Each page is its own chunk, loaded on first visit.
import path from "node:path";
import vue from "@vitejs/plugin-vue";
import frappeui from "frappe-ui/vite";
import { defineConfig } from "vite";

const here = import.meta.dirname;

export default defineConfig({
	plugins: [
		// Only the import rewriting: Desk serves the page, so no proxy, boot data or index.html.
		frappeui({ frappeProxy: false, jinjaBootData: false, buildConfig: false }),
		vue(),
	],
	define: { "process.env.NODE_ENV": JSON.stringify("production") },
	resolve: { alias: { "@": path.resolve(here, "src") } },
	build: {
		outDir: path.resolve(here, "../xero/public/frontend"),
		emptyOutDir: true,
		cssCodeSplit: false,
		lib: {
			entry: path.resolve(here, "src/main.js"),
			formats: ["es"],
			fileName: () => "xero-pages.js",
			cssFileName: "xero-pages",
		},
		rollupOptions: {
			output: {
				chunkFileNames: "chunks/[name]-[hash].js",
				// One stylesheet at a fixed path, which Desk links with a version query (boot.py).
				assetFileNames: (asset) =>
					asset.names?.some((n) => n.endsWith(".css"))
						? "xero-pages.css"
						: "assets/[name]-[hash][extname]",
			},
		},
	},
});

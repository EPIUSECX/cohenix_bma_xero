import preset from "frappe-ui/tailwind";

/** @type {import('tailwindcss').Config} */
export default {
	presets: [preset],
	theme: {
		extend: {
			// The face Desk loads. Frappe UI names it InterVar, which Desk never loads, so text fell
			// back to the system font.
			fontFamily: {
				sans: ["InterVariable", "Inter", "ui-sans-serif", "system-ui", "sans-serif"],
			},
		},
	},
	// Our pages and the Frappe UI components they render. Not frappe-ui's whole `content` export:
	// it also scans its docs site, which would bloat the stylesheet.
	content: ["./src/**/*.{vue,js}", "./node_modules/frappe-ui/src/components/**/*.{vue,js,ts}"],
};

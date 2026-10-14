import autoprefixer from "autoprefixer";
import tailwindcss from "tailwindcss";
import scopeToXeroUi from "./postcss-scope.js";

export default { plugins: [tailwindcss(), scopeToXeroUi(), autoprefixer()] };

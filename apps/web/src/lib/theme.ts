/** Renamed with the glass redesign: browsers that saved "light" or "system" under the old name now start
 *  in dark glass once, and keep whatever they pick from here on. */
export const THEME_COOKIE = "mindnest_theme_glass";
export const THEMES = ["system", "light", "dark"] as const;
export type Theme = (typeof THEMES)[number];

export function isTheme(value: string | undefined | null): value is Theme {
  return !!value && (THEMES as readonly string[]).includes(value);
}

/** Runs in <head> before the page paints, so nobody sees a flash of the wrong theme. Dark glass is the
 *  default; "system" follows the browser's setting and keeps following it while the page is open. */
export const THEME_BOOT_SCRIPT = `(function(){try{
var m=document.cookie.match(/(?:^|; )${THEME_COOKIE}=([^;]*)/);var c=m?m[1]:"dark";
var q=window.matchMedia("(prefers-color-scheme: dark)");
function apply(){var t=c==="light"||c==="dark"?c:(q.matches?"dark":"light");document.documentElement.setAttribute("data-theme",t);}
apply();if(c==="system"){q.addEventListener("change",apply);}
}catch(e){}})();`;

export function applyTheme(theme: Theme): void {
  document.cookie = `${THEME_COOKIE}=${theme}; path=/; max-age=31536000; samesite=lax`;
  const resolved =
    theme === "system" ? (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light") : theme;
  document.documentElement.setAttribute("data-theme", resolved);
}

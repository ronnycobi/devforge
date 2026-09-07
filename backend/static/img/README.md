# DevForge brand assets

Drop the logo files here with these exact names — the UI references them and
upgrades automatically (with a graceful gradient/text fallback until they exist):

- `devforge-mark.png` — the "DF" mark only. Used in the nav/sidebar logo square
  and the browser context. **Best as a transparent-background PNG or SVG** (a
  solid white background will show as a white box on the dark UI). If you have an
  SVG, save it as `devforge-mark.svg` and update the `{% static %}` references.

- `devforge-logo.png` — the full lockup (DF mark + DEVFORGE wordmark + tagline)
  on a dark/transparent background. Used on the login screen and the marketing
  footer, where a larger branded lockup on a dark panel looks best.

Recommended sizes: mark ≥ 256×256, full logo ≥ 800px wide. Transparent PNG or SVG
preferred so it sits cleanly on the dark theme.

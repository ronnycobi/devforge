"""Store screenshot studio (spec §17).

Turns the application's REAL screens into store-ready visuals. Two sources, and the
distinction is kept honest end to end:

  LiveCaptureSource  — a pixel capture of the *running* application. This needs the
                       app running under a headless browser / device simulator; that
                       infra is not configured here, so the source reports
                       unavailable and refuses rather than fake a capture.

  SchematicSource    — always available offline. Renders a device-framed LAYOUT from
                       the app's actual screen definitions (the screen's name and its
                       real component list, read from the Software Twin). It faithfully
                       represents the app's structure and is always labelled a
                       generated layout — never presented as a real device capture.

Store §17 rule: "Do not generate fake UI screenshots that don't represent the actual
application." Schematic previews are built strictly from the app's own screens, and
the UI/labels never claim they are photos of the running app. Real submission-grade
captures come from LiveCaptureSource once the app is running.
"""
from __future__ import annotations

import html
from dataclasses import dataclass

from apps.project_context.models import ContextKind
from apps.project_context.services import ProjectContext


@dataclass(frozen=True)
class DeviceSpec:
    slot: str
    label: str
    width: int
    height: int


# Representative store screenshot slots (portrait). Verify against current store
# docs before a live submission — these are the common required sizes.
DEVICE_SPECS = {
    "google_play": DeviceSpec("phone", "Phone", 1080, 1920),
    "apple_app_store": DeviceSpec("iphone_6_7", "iPhone 6.7\"", 1290, 2796),
    "huawei_appgallery": DeviceSpec("phone", "Phone", 1080, 1920),
}


def spec_for(provider_key: str) -> DeviceSpec:
    return DEVICE_SPECS.get(provider_key, DeviceSpec("phone", "Phone", 1080, 1920))


class ScreenshotError(Exception):
    pass


# --- sources -------------------------------------------------------------------
class ScreenshotSource:
    name = ""

    def is_available(self) -> bool:
        return False

    def render(self, *, screen_name, components, spec, app_name) -> dict:
        raise NotImplementedError


class LiveCaptureSource(ScreenshotSource):
    """Real capture of the running app (spec §17 pipeline: launch → navigate →
    capture). Requires a running app + headless browser/simulator, which is not
    configured here — so it refuses instead of faking a capture."""

    name = "live"

    def is_available(self) -> bool:
        return False

    def render(self, *, screen_name, components, spec, app_name):
        raise ScreenshotError(
            "Live device capture needs the application running under a headless "
            "browser or simulator, which is not configured here. Deploy/run the app "
            "to capture real submission-grade screenshots; DevForge does not fake them."
        )


class SchematicSource(ScreenshotSource):
    """Device-framed layout generated from the app's real screen definition."""

    name = "schematic"

    def is_available(self) -> bool:
        return True

    def render(self, *, screen_name, components, spec, app_name):
        svg = _render_svg(screen_name=screen_name, components=components,
                          spec=spec, app_name=app_name)
        return {"fmt": "svg", "svg": svg, "width": spec.width, "height": spec.height,
                "source": self.name}


def capture_source() -> ScreenshotSource:
    """Best available source: real capture if wired, else the honest schematic."""
    live = LiveCaptureSource()
    return live if live.is_available() else SchematicSource()


# --- schematic SVG renderer ----------------------------------------------------
def _render_svg(*, screen_name, components, spec, app_name) -> str:
    w, h = spec.width, spec.height
    name = html.escape((screen_name or "Screen")[:40])
    app = html.escape((app_name or "App")[:30])
    # A simple, honest wireframe: status/app bar with the real screen name, then a
    # block per real component. Scaled to the store slot's exact dimensions.
    pad = int(w * 0.06)
    bar_h = int(h * 0.09)
    blocks = []
    y = bar_h + pad
    block_h = int(h * 0.11)
    gap = int(h * 0.03)
    for comp in (components or [])[:6]:
        label = html.escape(str(comp)[:32])
        blocks.append(
            f'<rect x="{pad}" y="{y}" width="{w - 2 * pad}" height="{block_h}" '
            f'rx="{int(w*0.03)}" fill="#eef1f8" stroke="#d7deec"/>'
            f'<text x="{pad + int(w*0.04)}" y="{y + block_h // 2 + 14}" '
            f'font-family="Inter,Arial,sans-serif" font-size="{int(h*0.022)}" '
            f'fill="#33405e">{label}</text>'
        )
        y += block_h + gap
        if y > h - block_h:
            break
    if not blocks:
        blocks.append(
            f'<text x="{w//2}" y="{h//2}" text-anchor="middle" '
            f'font-family="Inter,Arial,sans-serif" font-size="{int(h*0.03)}" '
            f'fill="#8a93ad">{name}</text>'
        )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
        f'viewBox="0 0 {w} {h}" role="img" aria-label="{name} layout preview">'
        f'<rect width="{w}" height="{h}" fill="#ffffff"/>'
        f'<rect x="0" y="0" width="{w}" height="{bar_h}" fill="#4f7cff"/>'
        f'<text x="{pad}" y="{bar_h//2 + 16}" font-family="Inter,Arial,sans-serif" '
        f'font-size="{int(h*0.028)}" font-weight="700" fill="#ffffff">{name}</text>'
        f'<text x="{w-pad}" y="{bar_h//2 + 14}" text-anchor="end" '
        f'font-family="Inter,Arial,sans-serif" font-size="{int(h*0.02)}" '
        f'fill="#dbe4ff">{app}</text>'
        + "".join(blocks)
        + '</svg>'
    )


# --- reading the app's real screens --------------------------------------------
def app_screens(project) -> list[dict]:
    """The app's real screens from the Twin: name + actual component list."""
    ctx = ProjectContext(project)
    screens = []
    for e in ctx.by_kind(ContextKind.SCREEN):
        name = (e.title or "").replace("[mobile]", "").strip()
        if not name:
            continue
        components = e.data.get("components") if isinstance(e.data, dict) else None
        screens.append({"name": name, "components": components or []})
    return screens


def validate_dimensions(width: int, height: int, spec: DeviceSpec) -> bool:
    return width == spec.width and height == spec.height

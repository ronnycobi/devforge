"""Storefront generator (spec §32).

Emits REAL HTML into the site from the website's products: a shop index plus a page
per product, each with a working buy form that posts to the live checkout endpoint
(/sites/<subdomain>/checkout). The generated pages publish and serve like any other
content, and the buy form drives the real order → payment flow (manual works; card
gateways stay gated). Output is clean and accessible (lang, single h1) and all
product content is HTML-escaped.
"""
from __future__ import annotations

import html as html_lib

from apps.repositories.service import GitError, repo_for_project


class StorefrontError(Exception):
    pass


def _doc(title: str, main: str) -> str:
    t = html_lib.escape(title)
    return (
        f"<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        f"<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        f"<title>{t}</title></head><body>"
        f"<header><nav><a href=\"/\">Home</a> · <a href=\"/shop/\">Shop</a></nav></header>"
        f"<main>{main}</main></body></html>"
    )


def _buy_form(website, product) -> str:
    action = f"/sites/{website.subdomain}/checkout"
    return (
        f'<form method="post" action="{action}">'
        f'<input type="hidden" name="product_id" value="{product.id}">'
        f'<label>Quantity <input type="number" name="quantity" value="1" min="1"></label>'
        f'<label>Your name <input type="text" name="name"></label>'
        f'<label>Email <input type="email" name="email" required></label>'
        f'<button type="submit">Buy — {html_lib.escape(product.price_display)}</button>'
        f'</form>'
    )


def render_storefront(website) -> dict:
    products = list(website.products.filter(active=True))
    if not products:
        return {}
    files: dict[str, str] = {}

    cards = "".join(
        f'<article><h2><a href="/shop/{html_lib.escape(p.slug)}.html">{html_lib.escape(p.name)}</a></h2>'
        f'<p>{html_lib.escape(p.price_display)}</p>'
        f'{f"<p>{html_lib.escape(p.description[:160])}</p>" if p.description else ""}'
        f'{_buy_form(website, p)}</article>'
        for p in products
    )
    files["shop/index.html"] = _doc("Shop", f"<h1>Shop</h1>{cards}")

    for p in products:
        body = (
            f"<h1>{html_lib.escape(p.name)}</h1>"
            f"<p>{html_lib.escape(p.price_display)}</p>"
            f'{f"<p>{html_lib.escape(p.description)}</p>" if p.description else ""}'
            f"{_buy_form(website, p)}"
        )
        files[f"shop/{p.slug}.html"] = _doc(p.name, body)
    return files


def generate_storefront(website, *, user=None) -> dict:
    files = render_storefront(website)
    if not files:
        raise StorefrontError("Add at least one active product before generating the storefront.")
    repo = repo_for_project(website.project)
    if not repo.is_initialized:
        repo.init()
    repo.write_files(files)
    try:
        commit = repo.commit("Generate storefront pages")
    except GitError:
        commit = ""
    from apps.audit.service import record as audit
    audit("shop.storefront", actor=user, organization=website.project.organization,
          target=f"website:{website.id}", summary=f"{len(files)} page(s)",
          metadata={"commit": commit})
    return {"pages": len(files), "paths": sorted(files), "commit": commit}

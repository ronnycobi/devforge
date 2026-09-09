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


def _doc(website, title: str, main: str) -> str:
    t = html_lib.escape(title)
    return (
        f"<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        f"<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        f"<title>{t}</title></head><body>"
        f"<header><nav><a href=\"/\">Home</a> · <a href=\"/shop/\">Shop</a> · "
        f"<a href=\"/shop/cart.html\">Cart</a></nav></header>"
        f"<main>{main}</main>{_cart_script(website)}</body></html>"
    )


def _cart_script(website) -> str:
    """A small dependency-free cart: keeps selections in localStorage, and on the cart
    page renders line items and submits them to the checkout endpoint as `line`
    fields. Runs on the customer's own published site."""
    key = f"devforge_cart_{website.subdomain}"
    return (
        "<script>(function(){var KEY=" + _js_str(key) + ";"
        "function get(){try{return JSON.parse(localStorage.getItem(KEY))||[]}catch(e){return[]}}"
        "function save(c){try{localStorage.setItem(KEY,JSON.stringify(c))}catch(e){}}"
        "window.devforgeAdd=function(b){var c=get(),id=b.getAttribute('data-id');"
        "var f=c.filter(function(x){return x.id===id})[0];"
        "if(f){f.qty++}else{c.push({id:id,name:b.getAttribute('data-name'),price:+b.getAttribute('data-price'),qty:1})}"
        "save(c);b.textContent='Added \\u2713';setTimeout(function(){b.textContent='Add to cart'},1200)};"
        "var box=document.getElementById('devforge-cart-items');"
        "if(box){var c=get(),h='',total=0;"
        "c.forEach(function(x){var l=x.price*x.qty;total+=l;"
        "h+='<li>'+x.qty+' \\u00d7 '+x.name+' \\u2014 '+(l/100).toFixed(2)+'</li>'});"
        "box.innerHTML=h||'<li>Your cart is empty.</li>';"
        "var t=document.getElementById('devforge-cart-total');if(t)t.textContent=(total/100).toFixed(2);"
        "var form=document.getElementById('devforge-checkout');"
        "if(form)form.addEventListener('submit',function(){if(!c.length){return}"
        "c.forEach(function(x){var i=document.createElement('input');i.type='hidden';i.name='line';i.value=x.id+':'+x.qty;form.appendChild(i)});"
        "try{localStorage.removeItem(KEY)}catch(e){}})}"
        "})();</script>"
    )


def _js_str(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _add_button(product) -> str:
    return (
        f'<button type="button" onclick="devforgeAdd(this)" '
        f'data-id="{product.id}" data-name="{html_lib.escape(product.name)}" '
        f'data-price="{product.price_cents}">Add to cart</button>'
    )


def _buy_form(website, product) -> str:
    if not product.in_stock:
        return '<p class="devforge-oos">Out of stock</p>'
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
        f'{(_add_button(p) + " ") if p.in_stock else ""}{_buy_form(website, p)}</article>'
        for p in products
    )
    files["shop/index.html"] = _doc(website, "Shop", f"<h1>Shop</h1>{cards}")

    for p in products:
        body = (
            f"<h1>{html_lib.escape(p.name)}</h1>"
            f"<p>{html_lib.escape(p.price_display)}</p>"
            f'{f"<p>{html_lib.escape(p.description)}</p>" if p.description else ""}'
            f"{(_add_button(p) + ' ') if p.in_stock else ''}{_buy_form(website, p)}"
        )
        files[f"shop/{p.slug}.html"] = _doc(website, p.name, body)

    # Cart page — the JS in _cart_script renders line items and posts them to checkout.
    currency = products[0].currency
    cart_main = (
        "<h1>Your cart</h1>"
        '<ul id="devforge-cart-items"></ul>'
        f'<p>Total: <span id="devforge-cart-total">0.00</span> {html_lib.escape(currency)}</p>'
        f'<form id="devforge-checkout" method="post" action="/sites/{website.subdomain}/checkout">'
        '<label>Your name <input type="text" name="name"></label>'
        '<label>Email <input type="email" name="email" required></label>'
        '<button type="submit">Checkout</button></form>'
    )
    files["shop/cart.html"] = _doc(website, "Your cart", cart_main)
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

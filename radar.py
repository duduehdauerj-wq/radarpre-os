"""Radar de preços pessoal para Freguesia/Jacarepaguá (biblioteca padrão do Python)."""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import statistics
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config"
DATA = ROOT / "data"
USER_AGENT = "RadarMercado/1.0 (personal price tracker; contact configured by repository owner)"
TIMEOUT_SECONDS = 25


def load_json(path: Path, fallback):
    if not path.exists():
        return fallback
    with path.open("r", encoding="utf-8") as source:
        return json.load(source)


def save_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def normalize(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", str(value).lower())
    without_marks = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", without_marks).split())


def http_get(url: str, accept: str = "*/*") -> bytes | None:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept})
    try:
        with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return response.read()
    except (HTTPError, URLError, TimeoutError, OSError) as error:
        print(f"Fonte indisponível: {url.split('?')[0]} ({error})")
        return None


def get_json(url: str):
    body = http_get(url, "application/json")
    if body is None:
        return None
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        print(f"Resposta JSON inválida: {error}")
        return None


def parse_price(text: str) -> float | None:
    """Converte preço brasileiro de texto para número, sem aceitar preço zerado."""
    match = re.search(r"(?:R\$\s*)?(\d{1,3}(?:\.\d{3})*|\d+),(\d{2})", text)
    if not match:
        return None
    value = float(match.group(1).replace(".", "") + "." + match.group(2))
    return value if value > 0 else None


def product_matches(title: str, product: dict) -> bool:
    title_text = normalize(title)
    keywords = product.get("keywords") or normalize(product["name"]).split()
    required = [normalize(word) for word in keywords if normalize(word)]
    return all(word in title_text for word in required)


def mercadolivre_search(product: dict, default_shipping: float = 0.0) -> list[dict]:
    query = quote(product["name"])
    payload = get_json(f"https://api.mercadolibre.com/sites/MLB/search?q={query}&limit=30")
    if not isinstance(payload, dict):
        return []
    offers = []
    for item in payload.get("results", []):
        title = str(item.get("title", ""))
        price = item.get("price")
        if not title or not product_matches(title, product) or not isinstance(price, (int, float)) or price <= 0:
            continue
        shipping_info = item.get("shipping") or {}
        is_free = bool(shipping_info.get("free_shipping"))
        offers.append({
            "product": product["name"], "title": title, "store": "Mercado Livre",
            "price": float(price), "shipping": float(default_shipping), "online": True,
            "url": item.get("permalink", ""), "shipping_assumed": not is_free,
            "source": "Mercado Livre (API pública)",
        })
    return offers


class AmazonSearchParser(HTMLParser):
    """Extrai título, preço e link de cada cartão de busca, quando o site permite."""

    VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.items = []
        self.card = None
        self.stack = []
        self.capture = None
        self.capture_parts = []
        self.href = ""

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if self.card is None and tag == "div" and attributes.get("data-component-type") == "s-search-result":
            self.card = {"title": "", "price": "", "url": ""}
            self.stack = []
        if self.card is not None:
            if tag not in self.VOID_TAGS:
                self.stack.append(tag)
            classes = set((attributes.get("class") or "").split())
            if tag == "h2":
                self.capture, self.capture_parts = "h2", []
            elif tag == "span" and "a-offscreen" in classes:
                self.capture, self.capture_parts = "span", []
            elif tag == "a" and self.capture == "h2":
                self.href = attributes.get("href", "")

    def handle_data(self, data):
        if self.capture:
            self.capture_parts.append(data)

    def handle_endtag(self, tag):
        if self.card is None:
            return
        if tag == self.capture:
            value = " ".join(" ".join(self.capture_parts).split())
            if tag == "h2":
                self.card["title"] = value
                self.card["url"] = self.href
                self.href = ""
            elif tag == "span":
                self.card["price"] = value
            self.capture = None
            self.capture_parts = []
        if tag in self.stack:
            while self.stack:
                popped = self.stack.pop()
                if popped == tag:
                    break
            if not self.stack:
                if self.card["title"] and self.card["price"]:
                    self.items.append(self.card)
                self.card = None


def amazon_search(product: dict, default_shipping: float = 0.0) -> list[dict]:
    url = "https://www.amazon.com.br/s?" + urlencode({"k": product["name"]})
    body = http_get(url, "text/html")
    if body is None:
        return []
    parser = AmazonSearchParser()
    try:
        parser.feed(body.decode("utf-8", errors="replace"))
    except Exception as error:  # Um HTML inesperado não pode interromper outras fontes.
        print(f"Não consegui ler os resultados da Amazon: {error}")
        return []
    offers = []
    for item in parser.items:
        title = item["title"]
        price = parse_price(item["price"])
        if not product_matches(title, product) or price is None:
            continue
        href = item["url"]
        if href.startswith("/"):
            href = "https://www.amazon.com.br" + href
        offers.append({
            "product": product["name"], "title": title, "store": "Amazon Brasil",
            "price": price, "shipping": float(default_shipping), "online": True,
            "url": href, "shipping_assumed": True,
            "source": "Amazon Brasil (busca pública)",
        })
    return offers


def retailer_feed_search(feed: dict, products: list[dict], default_shipping: float = 0.0) -> list[dict]:
    """Lê um feed JSON opcional configurado pelo usuário, sem inventar URLs de lojas."""
    url = feed.get("url")
    if not url:
        return []
    payload = get_json(url)
    rows = payload if isinstance(payload, list) else payload.get("offers", []) if isinstance(payload, dict) else []
    offers = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        title = str(row.get("title") or row.get("name") or "")
        raw_price = row.get("price")
        try:
            price = float(raw_price) if isinstance(raw_price, (int, float)) else parse_price(str(raw_price or ""))
        except (TypeError, ValueError):
            price = None
        if not title or price is None or price <= 0:
            continue
        product = next((p for p in products if product_matches(title, p)), None)
        if product is None:
            continue
        offers.append({
            "product": product["name"], "title": title,
            "store": str(row.get("store") or feed.get("store") or feed.get("name") or "Loja local"),
            "price": price, "shipping": float(default_shipping), "online": bool(row.get("online", False)),
            "url": str(row.get("url") or ""), "shipping_assumed": False,
            "source": str(feed.get("name") or "Feed configurado"),
        })
    return offers


def gather_offers(products: list[dict], settings: dict) -> list[dict]:
    offers = []
    default_shipping = float(settings.get("online_shipping_default_brl", 0.0))
    for product in products:
        for enabled, collector in (
            (settings.get("mercadolivre_enabled", True), mercadolivre_search),
            (settings.get("amazon_enabled", True), amazon_search),
        ):
            if not enabled:
                continue
            try:
                offers.extend(collector(product, default_shipping))
            except Exception as error:
                print(f"Fonte falhou para {product['name']}: {error}")
            time.sleep(1.0)
    for feed in settings.get("retailer_feeds", []):
        try:
            offers.extend(retailer_feed_search(feed, products, default_shipping))
        except Exception as error:
            print(f"Feed de loja falhou ({feed.get('name', 'sem nome')}): {error}")
    return offers


def history_key(product_name: str, store: str) -> str:
    return normalize(product_name) + "|" + normalize(store)


def classify_offer(offer: dict, product: dict, history: dict, minimum_samples: int = 3) -> dict:
    """Marca uma oferta pelo preço-alvo ou por histórico suficiente; não cria promoção no primeiro dia."""
    current = float(offer["price"]) + float(offer.get("shipping", 0.0))
    rows = history.get(history_key(product["name"], offer["store"]), [])
    prices = [float(row["price"]) for row in rows if isinstance(row.get("price"), (int, float)) and row["price"] > 0]
    average = statistics.mean(prices) if len(prices) >= minimum_samples else None
    target = product.get("target_price")
    below_target = isinstance(target, (int, float)) and current <= float(target)
    discount = ((average - current) / average * 100) if average else 0.0
    historical_deal = average is not None and discount >= float(product.get("alert_below_average_percent", 15))
    is_deal = bool(below_target or historical_deal)
    if average is None:
        label = "abaixo do preço-alvo" if below_target else "sem histórico suficiente"
    elif discount >= 30:
        label = "excepcional"
    elif discount >= 20:
        label = "muito bom"
    elif is_deal:
        label = "bom"
    else:
        label = "normal"
    offer.update({
        "effective_price": round(current, 2),
        "historical_average": round(average, 2) if average is not None else None,
        "historical_discount_percent": round(max(discount, 0.0), 1) if average else None,
        "deal": is_deal,
        "deal_label": label,
    })
    return offer


def record_history(offers: list[dict], products: list[dict], history: dict, keep_days: int = 365):
    names = {normalize(product["name"]): product["name"] for product in products}
    now = datetime.now(timezone.utc)
    for offer in offers:
        name = names.get(normalize(offer["product"]))
        if name is None:
            continue
        history.setdefault(history_key(name, offer["store"]), []).append({
            "date": now.isoformat(), "price": round(float(offer["price"]), 2),
        })
    cutoff = now - timedelta(days=int(keep_days))
    for key, rows in list(history.items()):
        kept = []
        for row in rows:
            try:
                stamp = datetime.fromisoformat(row["date"])
                if stamp.tzinfo is None:
                    stamp = stamp.replace(tzinfo=timezone.utc)
                if stamp >= cutoff:
                    kept.append(row)
            except (KeyError, TypeError, ValueError):
                continue
        if kept:
            history[key] = kept
        else:
            del history[key]
    return history


def new_deals_to_alert(offers: list[dict], alert_state: dict) -> list[dict]:
    fresh = []
    for offer in offers:
        if not offer.get("deal"):
            continue
        key = history_key(offer["product"], offer["store"])
        previous = alert_state.get(key)
        current = float(offer["effective_price"])
        if previous is None or current < float(previous.get("price", float("inf"))) * 0.99:
            fresh.append(offer)
    return fresh


def mark_alerts_sent(offers: list[dict], alert_state: dict):
    for offer in offers:
        alert_state[history_key(offer["product"], offer["store"])] = {
            "price": float(offer["effective_price"]), "date": datetime.now(timezone.utc).isoformat(),
        }


def shopping_suggestions(lists: dict, offers: list[dict]) -> dict:
    """Listas consultam somente os preços já coletados; não alteram o radar global."""
    result = {}
    for owner, items in lists.items():
        suggestions = []
        for item in items:
            product_name = str(item.get("product_name", ""))
            matches = [offer for offer in offers if normalize(offer["product"]) == normalize(product_name)]
            best = min(matches, key=lambda offer: offer["effective_price"]) if matches else None
            suggestions.append({
                "product_name": product_name, "quantity": max(1, int(item.get("quantity", 1))),
                "offer": best,
            })
        result[owner] = suggestions
    return result


def discover_nearby_stores(settings: dict, seed_data: dict, cache: dict) -> dict:
    """Descobre supermercados no OpenStreetMap; conserva cache caso a fonte falhe."""
    now = datetime.now(timezone.utc)
    refreshed = cache.get("updated_at")
    try:
        cache_fresh = refreshed and now - datetime.fromisoformat(refreshed) < timedelta(days=7)
    except (TypeError, ValueError):
        cache_fresh = False
    if cache_fresh:
        return cache

    center = cache.get("center")
    if not center:
        query = quote(settings.get("region", "Freguesia, Jacarepaguá, Rio de Janeiro, RJ"))
        result = get_json(f"https://nominatim.openstreetmap.org/search?format=json&limit=1&q={query}")
        if isinstance(result, list) and result:
            center = {"lat": float(result[0]["lat"]), "lon": float(result[0]["lon"])}
    if not center:
        print("Não consegui localizar a região no OpenStreetMap; vou manter as lojas já cadastradas.")
        return cache

    radius_m = int(float(settings.get("radius_km", 12)) * 1000)
    lat, lon = center["lat"], center["lon"]
    query = f"[out:json][timeout:25];(node(around:{radius_m},{lat},{lon})[shop=supermarket];way(around:{radius_m},{lat},{lon})[shop=supermarket];relation(around:{radius_m},{lat},{lon})[shop=supermarket];);out center tags;"
    response = http_get("https://overpass-api.de/api/interpreter?data=" + quote(query), "application/json")
    if response is None:
        return cache
    try:
        payload = json.loads(response.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return cache
    stores = []
    for element in payload.get("elements", []):
        tags = element.get("tags") or {}
        name = tags.get("name") or tags.get("brand")
        if not name:
            continue
        position = element.get("center") or element
        stores.append({
            "name": name,
            "brand": tags.get("brand", name),
            "neighborhood": tags.get("addr:suburb") or tags.get("addr:neighbourhood") or "",
            "address": " ".join(filter(None, [tags.get("addr:street"), tags.get("addr:housenumber")])),
            "lat": position.get("lat"), "lon": position.get("lon"),
            "source": "OpenStreetMap",
        })
    return {"center": center, "updated_at": now.isoformat(), "stores": stores}


def send_telegram(messages: list[str], token: str = "", chat_id: str = "") -> bool:
    if not messages:
        return True
    if not token or not chat_id:
        print("Telegram não configurado: os Secrets ainda não foram adicionados; pulei o envio.")
        return False
    from urllib.parse import urlencode as form_encode
    all_sent = True
    for message in messages:
        body = form_encode({"chat_id": chat_id, "text": message, "disable_web_page_preview": "true"}).encode("utf-8")
        request = Request(
            f"https://api.telegram.org/bot{token}/sendMessage", data=body,
            headers={"User-Agent": USER_AGENT, "Content-Type": "application/x-www-form-urlencoded"},
        )
        try:
            with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
                result = json.loads(response.read().decode("utf-8"))
                if not result.get("ok"):
                    print("Telegram recusou uma mensagem; confira o token e o chat ID.")
                    all_sent = False
        except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
            print(f"Falha ao enviar Telegram: {error}")
            all_sent = False
    return all_sent


def format_alerts(deals: list[dict]) -> list[str]:
    messages = []
    for offer in deals:
        shipping_note = "Frete zero assumido; confira no anúncio." if offer.get("shipping_assumed") else ""
        average = f"\nMédia histórica: R$ {offer['historical_average']:.2f}" if offer.get("historical_average") else ""
        url = f"\n{offer['url']}" if offer.get("url") else ""
        messages.append(
            f"🔥 OFERTA — {offer['product']}\n{offer['store']}: R$ {offer['price']:.2f} "
            f"({offer['deal_label']}){average}\n{shipping_note}{url}\nConfirme preço, estoque e condições."
        )
    return messages


def render_dashboard(offers: list[dict], products: list[dict], seed_data: dict, discovered: dict, lists: dict):
    DATA.mkdir(parents=True, exist_ok=True)
    rows = []
    for offer in sorted(offers, key=lambda item: item["effective_price"]):
        rows.append(
            "<tr><td>{}</td><td>{}</td><td>R$ {:.2f}</td><td>{}</td><td>{}</td><td><a href=\"{}\">Abrir</a></td></tr>".format(
                html.escape(offer["product"]), html.escape(offer["store"]), offer["effective_price"],
                html.escape(offer["deal_label"]), html.escape(offer["source"]), html.escape(offer["url"], quote=True),
            )
        )
    offer_rows = "\n".join(rows) or "<tr><td colspan=\"6\">Nenhum preço coletado. Adicione produtos ao radar e confira se as fontes online estão disponíveis.</td></tr>"
    store_rows = []
    priority = [normalize(value) for value in seed_data.get("route_priority", [])]
    combined = seed_data.get("candidate_chains", []) + discovered.get("stores", [])
    seen = set()
    for store in combined:
        name = str(store.get("name", ""))
        key = normalize(name)
        if not key or key in seen:
            continue
        seen.add(key)
        is_priority = any(value in key or key in value for value in priority)
        address = store.get("address") or store.get("neighborhood") or "endereço não confirmado"
        store_rows.append(f"<li>{'⭐ ' if is_priority else ''}{html.escape(name)} — {html.escape(str(address))}</li>")
    lists_html = []
    for owner, items in lists.items():
        count = len(items) if isinstance(items, list) else 0
        lists_html.append(f"<li>{html.escape(str(owner))}: {count} item(ns) configurado(s)</li>")
    updated = datetime.now().astimezone().strftime("%d/%m/%Y %H:%M")
    page = f"""<!doctype html><html lang="pt-BR"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Radar de Mercado</title><style>body{{font:16px system-ui;max-width:1150px;margin:2rem auto;padding:0 1rem;color:#222}}table{{width:100%;border-collapse:collapse}}th,td{{padding:.65rem;border-bottom:1px solid #ddd;text-align:left}}th{{background:#f2f2f2}}.note{{background:#f5f7fa;padding:1rem;border-radius:.5rem}}</style>
<h1>Radar de Mercado — Freguesia/Jacarepaguá</h1><p>Atualizado em {updated}.</p>
<p class="note">Frete online considerado R$ 0,00 por padrão. Nenhum custo de Uber/deslocamento é aplicado. Confirme preço, estoque e frete final antes de comprar.</p>
<h2>Ofertas monitoradas</h2><table><thead><tr><th>Produto</th><th>Fonte/loja</th><th>Preço efetivo</th><th>Classificação</th><th>Origem</th><th>Link</th></tr></thead><tbody>{offer_rows}</tbody></table>
<h2>Listas independentes</h2><ul>{''.join(lists_html) or '<li>Sem listas configuradas.</li>'}</ul>
<h2>Lojas cadastradas e encontradas</h2><p>As lojas prioritárias aparecem com estrela. Cadastro de loja não significa que exista uma fonte automatizada de preço.</p><ul>{''.join(store_rows)}</ul></html>"""
    (DATA / "dashboard.html").write_text(page, encoding="utf-8")


def validate_config(products: list[dict], lists: dict):
    if not isinstance(products, list):
        raise ValueError("config/products.json precisa conter uma lista JSON.")
    for index, product in enumerate(products):
        if not isinstance(product, dict) or not str(product.get("name", "")).strip():
            raise ValueError(f"Produto na posição {index + 1} precisa ter um campo name.")
    if not isinstance(lists, dict):
        raise ValueError("config/shopping_lists.json precisa ser um objeto JSON com nomes de listas.")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Coleta preços e atualiza painel e histórico do radar.")
    parser.add_argument("--offline", action="store_true", help="Não consulta fontes online; útil para validar configuração e painel.")
    args = parser.parse_args(argv)

    products = load_json(CONFIG / "products.json", [])
    settings = load_json(CONFIG / "settings.json", {})
    seed_data = load_json(CONFIG / "stores.json", {})
    lists = load_json(CONFIG / "shopping_lists.json", {})
    validate_config(products, lists)

    history = load_json(DATA / "history.json", {})
    alert_state = load_json(DATA / "alerts.json", {})
    geo_cache = load_json(DATA / "geocoded.json", {})
    discovered_cache = load_json(DATA / "stores_discovered.json", {})
    if discovered_cache:
        geo_cache.update(discovered_cache)
    if args.offline:
        discovered = load_json(DATA / "stores_discovered.json", {})
        offers = []
    else:
        discovered = discover_nearby_stores(settings, seed_data, geo_cache)
        if discovered:
            save_json(DATA / "geocoded.json", {"center": discovered.get("center"), "updated_at": discovered.get("updated_at")})
            save_json(DATA / "stores_discovered.json", discovered)
        if products:
            offers = gather_offers(products, settings)
        else:
            print("Radar global vazio: adicione os produtos desejados em config/products.json.")
            offers = []

    minimum_samples = int(settings.get("history_min_samples_for_deal", 3))
    product_map = {normalize(product["name"]): product for product in products}
    for offer in offers:
        product = product_map.get(normalize(offer["product"]))
        if product:
            classify_offer(offer, product, history, minimum_samples)
    deals = new_deals_to_alert(offers, alert_state)
    record_history(offers, products, history, int(settings.get("history_days", 365)))
    suggestions = shopping_suggestions(lists, offers)

    save_json(DATA / "history.json", history)
    render_dashboard(offers, products, seed_data, discovered, lists)

    telegram_messages = format_alerts(deals)
    sent = send_telegram(telegram_messages, token=os.getenv("TELEGRAM_BOT_TOKEN", ""), chat_id=os.getenv("TELEGRAM_CHAT_ID", ""))
    if sent and deals:
        mark_alerts_sent(deals, alert_state)
    save_json(DATA / "alerts.json", alert_state)
    print(f"Concluído: {len(offers)} preços; {len(deals)} alertas novos; {len(discovered.get('stores', []))} lojas OSM.")


if __name__ == "__main__":
    main()

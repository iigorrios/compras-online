"""Extrai nome, foto e preço de uma página de produto.

Usa os metadados que a maioria das lojas publica para o Google/redes sociais:
JSON-LD (schema.org/Product), Open Graph e microdados (itemprop="price").
Nem toda loja permite leitura automática (algumas bloqueiam robôs); nesses
casos o site deixa preencher o preço manualmente.
"""
from __future__ import annotations

import json
import re
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

LOJAS_CONHECIDAS = {
    "mercadolivre": "Mercado Livre",
    "mercadolibre": "Mercado Livre",
    "amazon": "Amazon",
    "magazineluiza": "Magalu",
    "magalu": "Magalu",
    "americanas": "Americanas",
    "casasbahia": "Casas Bahia",
    "pontofrio": "Ponto",
    "extra": "Extra",
    "shopee": "Shopee",
    "aliexpress": "AliExpress",
    "kabum": "KaBuM!",
    "submarino": "Submarino",
    "carrefour": "Carrefour",
    "leroymerlin": "Leroy Merlin",
    "fastshop": "Fast Shop",
    "netshoes": "Netshoes",
    "centauro": "Centauro",
    "shein": "Shein",
    "temu": "Temu",
}


def nome_loja(url: str) -> str:
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    for chave, nome in LOJAS_CONHECIDAS.items():
        if chave in host:
            return nome
    partes = host.split(".")
    return partes[0].capitalize() if partes and partes[0] else "Loja"


def parse_preco(valor) -> float | None:
    """Converte '1.299,90', 'R$ 1299.90', 1299.9 etc. em float."""
    if valor is None:
        return None
    if isinstance(valor, (int, float)):
        return float(valor) if valor > 0 else None
    texto = re.sub(r"[^\d,\.]", "", str(valor))
    if not texto:
        return None
    if "," in texto and "." in texto:
        # o separador que aparece por último é o decimal
        if texto.rfind(",") > texto.rfind("."):
            texto = texto.replace(".", "").replace(",", ".")
        else:
            texto = texto.replace(",", "")
    elif "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    elif texto.count(".") > 1 or re.fullmatch(r"\d{1,3}\.\d{3}", texto):
        # "1.299.000" ou "12.345" → ponto como separador de milhar
        texto = texto.replace(".", "")
    try:
        numero = float(texto)
    except ValueError:
        return None
    return numero if numero > 0 else None


def _itens_jsonld(soup: BeautifulSoup):
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            dados = json.loads(tag.string or tag.get_text() or "")
        except (json.JSONDecodeError, TypeError):
            continue
        pilha = [dados]
        while pilha:
            item = pilha.pop()
            if isinstance(item, list):
                pilha.extend(item)
            elif isinstance(item, dict):
                yield item
                for chave in ("@graph", "mainEntity", "itemListElement"):
                    if chave in item:
                        pilha.append(item[chave])


def _tipo(item: dict) -> list[str]:
    t = item.get("@type", [])
    return [t] if isinstance(t, str) else list(t)


def _preco_offers(offers) -> float | None:
    if isinstance(offers, list):
        precos = [p for p in (_preco_offers(o) for o in offers) if p]
        return min(precos) if precos else None
    if isinstance(offers, dict):
        for chave in ("price", "lowPrice"):
            preco = parse_preco(offers.get(chave))
            if preco:
                return preco
        spec = offers.get("priceSpecification")
        if spec:
            return _preco_offers(spec)
        if "offers" in offers:
            return _preco_offers(offers["offers"])
    return None


def _imagem(valor) -> str | None:
    if isinstance(valor, str):
        return valor
    if isinstance(valor, list) and valor:
        return _imagem(valor[0])
    if isinstance(valor, dict):
        return valor.get("url") or valor.get("contentUrl")
    return None


def _meta(soup: BeautifulSoup, *nomes: str) -> str | None:
    for nome in nomes:
        tag = soup.find("meta", attrs={"property": nome}) or soup.find(
            "meta", attrs={"name": nome}
        ) or soup.find("meta", attrs={"itemprop": nome})
        if tag and tag.get("content"):
            return tag["content"].strip()
    return None


def extrair_de_html(html: str, url: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    nome = imagem = None
    preco = None

    for item in _itens_jsonld(soup):
        if "Product" in _tipo(item) or "ProductGroup" in _tipo(item):
            nome = nome or item.get("name")
            imagem = imagem or _imagem(item.get("image"))
            preco = preco or _preco_offers(item.get("offers"))
            if "hasVariant" in item and not preco:
                preco = _preco_offers(
                    [v.get("offers") for v in item["hasVariant"] if isinstance(v, dict)]
                )

    preco = preco or parse_preco(
        _meta(soup, "product:price:amount", "og:price:amount", "price", "twitter:data1")
    )
    if not preco:
        tag = soup.find(attrs={"itemprop": "price"})
        if tag:
            preco = parse_preco(tag.get("content") or tag.get_text())

    nome = nome or _meta(soup, "og:title", "twitter:title")
    if not nome and soup.title:
        nome = soup.title.get_text(strip=True)
    imagem = imagem or _meta(soup, "og:image", "og:image:secure_url", "twitter:image")

    if imagem:
        imagem = urljoin(url, imagem)

    return {
        "nome": (nome or "").strip()[:200] or None,
        "imagem": imagem,
        "preco": round(preco, 2) if preco else None,
        "loja": nome_loja(url),
    }


def extrair(url: str, timeout: int = 12) -> dict:
    """Baixa a página e devolve {'nome','imagem','preco','loja','erro'}."""
    resultado = {"nome": None, "imagem": None, "preco": None, "loja": nome_loja(url), "erro": None}
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
        resp.raise_for_status()
    except requests.RequestException as exc:
        resultado["erro"] = f"Não foi possível abrir a página ({exc.__class__.__name__})."
        return resultado

    resultado.update(extrair_de_html(resp.text, resp.url))
    if not resultado["preco"]:
        resultado["erro"] = "Não encontrei o preço automaticamente — preencha manualmente."
    return resultado

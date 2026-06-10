"""Fetch the most recent post from the NHI blog.

Best-effort and resilient: tries common RSS/Atom feeds first (stable, structured),
then falls back to scraping the listing page for the first article link. Returns
``{title, url, text}`` or ``None`` if nothing could be parsed.
"""
import logging
import re
import xml.etree.ElementTree as ET
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

log = logging.getLogger("digest.blog")

_TIMEOUT = httpx.Timeout(30.0)
_FEED_PATHS = ["/rss.xml", "/feed", "/rss", "/feed.xml", "/atom.xml"]


async def _get(client: httpx.AsyncClient, url: str) -> httpx.Response | None:
    try:
        resp = await client.get(url, follow_redirects=True)
        if resp.status_code == 200:
            return resp
    except httpx.RequestError as exc:
        log.debug("fetch failed %s: %s", url, exc)
    return None


def _parse_feed(xml_text: str) -> dict | None:
    """Return the first item of an RSS or Atom feed."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None
    # RSS: channel/item ; Atom: {ns}entry
    item = root.find(".//item")
    if item is not None:
        title = item.findtext("title")
        link = item.findtext("link")
        desc = item.findtext("description") or ""
        if title and link:
            return {"title": title.strip(), "url": link.strip(), "text": _strip_html(desc)}
    ns = {"a": "http://www.w3.org/2005/Atom"}
    entry = root.find(".//a:entry", ns)
    if entry is not None:
        title = entry.findtext("a:title", namespaces=ns)
        link_el = entry.find("a:link", ns)
        link = link_el.get("href") if link_el is not None else None
        summary = entry.findtext("a:summary", namespaces=ns) or ""
        if title and link:
            return {"title": title.strip(), "url": link.strip(), "text": _strip_html(summary)}
    return None


def _strip_html(html: str) -> str:
    return BeautifulSoup(html, "html.parser").get_text(" ", strip=True)


def _scrape_listing(html: str, base_url: str) -> dict | None:
    """Heuristic: first link that points at an individual blog post."""
    soup = BeautifulSoup(html, "html.parser")
    base_path = urlparse(base_url).path.rstrip("/")  # e.g. /blog
    for a in soup.find_all("a", href=True):
        href = a["href"]
        path = urlparse(href).path
        # A post lives *under* the listing path, with a slug segment after it.
        if base_path and path.startswith(base_path + "/") and len(path) > len(base_path) + 1:
            title = a.get_text(" ", strip=True)
            if title and len(title) > 8:  # skip nav/icon links
                return {"title": title, "url": urljoin(base_url, href), "text": ""}
    return None


async def _extract_article_text(client: httpx.AsyncClient, url: str) -> str:
    resp = await _get(client, url)
    if resp is None:
        return ""
    soup = BeautifulSoup(resp.text, "html.parser")
    paragraphs = [p.get_text(" ", strip=True) for p in soup.find_all("p")]
    text = "\n".join(p for p in paragraphs if p)
    return re.sub(r"\n{3,}", "\n\n", text)


async def fetch_latest_post(blog_url: str) -> dict | None:
    async with httpx.AsyncClient(timeout=_TIMEOUT, headers={"User-Agent": "IdentityHub-Digest"}) as client:
        # 1) RSS/Atom feeds (most reliable).
        for path in _FEED_PATHS:
            resp = await _get(client, urljoin(blog_url, path))
            if resp is None:
                continue
            post = _parse_feed(resp.text)
            if post:
                if not post["text"]:
                    post["text"] = await _extract_article_text(client, post["url"])
                log.info("Latest post via feed: %s", post["title"])
                return post

        # 2) Fall back to scraping the listing page.
        resp = await _get(client, blog_url)
        if resp is None:
            log.warning("Could not reach blog at %s", blog_url)
            return None
        post = _scrape_listing(resp.text, blog_url)
        if not post:
            log.warning("Could not find a post link on %s", blog_url)
            return None
        post["text"] = await _extract_article_text(client, post["url"])
        log.info("Latest post via scrape: %s", post["title"])
        return post

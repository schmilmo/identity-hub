"""Tests for the NHI Blog Digest worker.

Pure parsing helpers plus an end-to-end run_once with the blog fetch + LLM
mocked, the fake Jira client, and fakeredis for dedup.
"""
import pytest

from app.config import get_settings
from app.database import SessionLocal, engine, init_db
from app.digest import blog
from app.digest import run as digest_run
from app.models import JiraConnection, User
from app.security.crypto import encrypt


def test_parse_rss_feed_returns_first_item():
    rss = """<?xml version="1.0"?>
    <rss version="2.0"><channel>
      <title>Oasis Blog</title>
      <item>
        <title>NHIs are everywhere</title>
        <link>https://oasis.security/blog/nhis-everywhere</link>
        <description>&lt;p&gt;Service accounts sprawl.&lt;/p&gt;</description>
      </item>
      <item><title>Older</title><link>https://oasis.security/blog/older</link></item>
    </channel></rss>"""
    post = blog._parse_feed(rss)
    assert post["title"] == "NHIs are everywhere"
    assert post["url"].endswith("/nhis-everywhere")
    assert "sprawl" in post["text"]  # HTML stripped from description


def test_scrape_listing_finds_first_post_link():
    html = """
    <html><body>
      <a href="/blog">Blog</a>
      <a href="/blog/stale-service-accounts">Stale service accounts are a risk</a>
      <a href="/blog/another-post">Another post</a>
    </body></html>"""
    post = blog._scrape_listing(html, "https://oasis.security/blog")
    assert post["url"] == "https://oasis.security/blog/stale-service-accounts"
    assert "Stale service accounts" in post["title"]


@pytest.mark.asyncio
async def test_run_once_creates_ticket_and_dedups(monkeypatch, mock_jira):
    # Isolate engine connections from other tests' event loops.
    await engine.dispose()
    await init_db()
    try:
        # Seed the digest user + an (encrypted) Jira connection directly.
        ct, nonce = encrypt("tok-123")
        async with SessionLocal() as db:
            user = User(email="digest@example.com", password_hash="x")
            db.add(user)
            await db.flush()
            db.add(
                JiraConnection(
                    user_id=user.id,
                    site_url="acme.atlassian.net",
                    jira_email="d@e.com",
                    api_token_ciphertext=ct,
                    api_token_nonce=nonce,
                )
            )
            await db.commit()

        s = get_settings()
        monkeypatch.setattr(s, "digest_user_email", "digest@example.com")
        monkeypatch.setattr(s, "digest_project_key", "NHI")

        async def fake_fetch(url):
            return {"title": "Post X", "url": "https://b/x", "text": "body"}

        async def fake_summarize(title, body):
            return "A concise summary."

        monkeypatch.setattr(blog, "fetch_latest_post", fake_fetch)
        monkeypatch.setattr(digest_run.llm, "summarize", fake_summarize)

        key = await digest_run.run_once()
        assert key and key.startswith("NHI-")

        ticket = mock_jira["acme.atlassian.net"][-1]
        assert ticket["title"].startswith("NHI Blog Digest: Post X")
        assert "nhi-blog-digest" in ticket["labels"]
        assert "A concise summary." in ticket["description"]
        assert "https://b/x" in ticket["description"]

        # Second run: same post URL → deduped, no new ticket.
        assert await digest_run.run_once() is None
        assert len(mock_jira["acme.atlassian.net"]) == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_run_once_skips_when_unconfigured(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "digest_user_email", "")
    monkeypatch.setattr(s, "digest_project_key", "")
    assert await digest_run.run_once() is None

"""NHI Blog Digest — periodic worker (separate container, shared codebase).

Each run: fetch the latest oasis.security/blog post → (dedup against the last
one via Redis) → summarize with a configurable free LLM → create a Jira ticket
under the configured user's connection. Runs forever, sleeping
``DIGEST_INTERVAL_SECONDS`` between runs; resilient to per-run failures.

Run: ``python -m app.digest.run`` (or `docker compose --profile digest up`).
"""
import asyncio
import logging

from sqlalchemy import select

from app import redis_client
from app.config import get_settings
from app.database import SessionLocal, init_db
from app.digest import blog, llm
from app.models import JiraConnection, User
from app.services.findings_service import client_for
from app.services.jira_client import JiraError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("digest")

_LAST_URL_KEY = "digest:last_url"


async def run_once() -> str | None:
    """Do one digest cycle. Returns the created issue key, or None if skipped."""
    s = get_settings()
    if not s.digest_configured:
        log.info("Digest not configured (set DIGEST_USER_EMAIL + DIGEST_PROJECT_KEY); skipping.")
        return None

    post = await blog.fetch_latest_post(s.digest_blog_url)
    if not post:
        log.warning("No blog post found; skipping.")
        return None

    redis = redis_client.get_redis()
    if await redis.get(_LAST_URL_KEY) == post["url"]:
        log.info("Latest post unchanged (%s); already digested.", post["url"])
        return None

    summary = await llm.summarize(post["title"], post["text"])

    async with SessionLocal() as db:
        result = await db.execute(select(User).where(User.email == s.digest_user_email))
        user = result.scalar_one_or_none()
        if user is None:
            log.error("Digest user %s not found.", s.digest_user_email)
            return None
        result = await db.execute(
            select(JiraConnection).where(JiraConnection.user_id == user.id)
        )
        conn = result.scalar_one_or_none()
        if conn is None:
            log.error("Digest user %s has no Jira connection.", s.digest_user_email)
            return None

        client = client_for(conn)
        description = f"{summary}\n\nSource: {post['url']}"
        try:
            created = await client.create_issue(
                project_key=s.digest_project_key,
                summary=f"NHI Blog Digest: {post['title']}",
                description=description,
                labels=["nhi-blog-digest"],
            )
        except JiraError as exc:
            log.error("Jira rejected digest ticket: %s", exc.message)
            return None

    await redis.set(_LAST_URL_KEY, post["url"])
    log.info("Created digest ticket %s for post: %s", created["key"], post["title"])
    return created["key"]


async def main() -> None:
    s = get_settings()
    log.info(
        "Digest worker starting (every %ss, blog=%s, llm=%s/%s).",
        s.digest_interval_seconds, s.digest_blog_url, s.llm_base_url, s.llm_model,
    )
    await init_db()
    await llm.ensure_model()
    while True:
        try:
            await run_once()
        except Exception:  # noqa: BLE001 — never let the loop die
            log.exception("Digest run failed; will retry next interval.")
        await asyncio.sleep(s.digest_interval_seconds)


if __name__ == "__main__":
    asyncio.run(main())

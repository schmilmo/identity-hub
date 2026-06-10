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
from app.models import DigestSubscription, JiraConnection
from app.services.findings_service import client_for
from app.services.jira_client import JiraError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("digest")


def _dedup_key(user_id: str, project_key: str) -> str:
    # Per (user, project): each subscribed project gets a given post once.
    return f"digest:last:{user_id}:{project_key}"


async def run_once() -> list[str]:
    """Do one digest cycle across all user subscriptions. Returns created keys.

    Fetches and summarizes the latest post once, then files a ticket for each
    subscription whose project hasn't seen this post yet, using that user's own
    Jira connection.
    """
    s = get_settings()
    post = await blog.fetch_latest_post(s.digest_blog_url)
    if not post:
        log.warning("No blog post found; skipping.")
        return []

    redis = redis_client.get_redis()
    created: list[str] = []

    async with SessionLocal() as db:
        subs = (await db.execute(select(DigestSubscription))).scalars().all()
        if not subs:
            log.info("No digest subscriptions; nothing to do.")
            return []

        # Which subscriptions still need this post? (skip the LLM if none do)
        pending = [
            sub
            for sub in subs
            if await redis.get(_dedup_key(sub.user_id, sub.project_key)) != post["url"]
        ]
        if not pending:
            log.info("Latest post already digested for all subscriptions.")
            return []

        summary = await llm.summarize(post["title"], post["text"])
        description = f"{summary}\n\nSource: {post['url']}"
        # Jira caps the summary (title) at 255 chars; the scrape fallback can
        # yield a long title, so truncate defensively.
        ticket_title = f"NHI Blog Digest: {post['title']}"[:255]

        conn_cache: dict[str, JiraConnection | None] = {}
        for sub in pending:
            if sub.user_id not in conn_cache:
                result = await db.execute(
                    select(JiraConnection).where(
                        JiraConnection.user_id == sub.user_id
                    )
                )
                conn_cache[sub.user_id] = result.scalar_one_or_none()
            conn = conn_cache[sub.user_id]
            if conn is None:
                log.warning("User %s has no Jira connection; skipping.", sub.user_id)
                continue

            client = client_for(conn)
            try:
                result = await client.create_issue(
                    project_key=sub.project_key,
                    summary=ticket_title,
                    description=description,
                    labels=["nhi-blog-digest"],
                )
            except JiraError as exc:
                log.error(
                    "Jira rejected digest ticket for %s/%s: %s",
                    sub.user_id, sub.project_key, exc.message,
                )
                continue

            # Cross-reference back to the finding's detail page (best-effort).
            app_url = f"{s.frontend_origin.rstrip('/')}/findings/{result['key']}"
            try:
                await client.add_remote_link(result["key"], app_url, "View in IdentityHub")
            except JiraError:
                pass

            await redis.set(_dedup_key(sub.user_id, sub.project_key), post["url"])
            created.append(result["key"])
            log.info("Created digest ticket %s in %s", result["key"], sub.project_key)

    log.info("Digest cycle done: %d ticket(s) created.", len(created))
    return created


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

import asyncio
import time

from memer.helpers.meme_cache_service import MemeCacheService


class DummySubreddit:
    async def hot(self, limit=25):
        if False:
            yield None


class DummyReddit:
    async def subreddit(self, name):
        return DummySubreddit()


class DummyCacheManager:
    def get_all_cached_keywords(self):
        return [("test", False)]

    async def refresh_keywords(self, keywords, fetch_fn):
        for kw, nsfw in keywords:
            await fetch_fn(kw, nsfw)


async def old_style(iterations=1000):
    reddit = DummyReddit()
    cache_mgr = DummyCacheManager()

    async def run_once():
        keywords = cache_mgr.get_all_cached_keywords()
        if not keywords:
            return

        async def fetch_fn(keyword, nsfw):
            fallback_subs = ["memes", "dankmemes", "funny"]
            semaphore = asyncio.Semaphore(2)

            async def fetch_sub(sub_name):
                async with semaphore:
                    sub = await reddit.subreddit(sub_name)
                    async for _ in sub.hot(limit=25):
                        pass
                    return []

            await asyncio.gather(*(fetch_sub(name) for name in fallback_subs))

        await cache_mgr.refresh_keywords(keywords, fetch_fn)

    start = time.perf_counter()
    for _ in range(iterations):
        await run_once()
    return time.perf_counter() - start


async def new_style(iterations=1000):
    cache_mgr = DummyCacheManager()
    svc = MemeCacheService(DummyReddit(), {})
    svc.cache_mgr = cache_mgr

    async def run_once():
        keywords = cache_mgr.get_all_cached_keywords()
        if not keywords:
            return
        await cache_mgr.refresh_keywords(keywords, svc._fetch_keyword_posts)

    start = time.perf_counter()
    for _ in range(iterations):
        await run_once()
    return time.perf_counter() - start


async def main():
    iterations = 1000
    t_old = await old_style(iterations)
    t_new = await new_style(iterations)
    print(f"Old style: {t_old:.4f}s\nNew style: {t_new:.4f}s")


if __name__ == "__main__":
    asyncio.run(main())

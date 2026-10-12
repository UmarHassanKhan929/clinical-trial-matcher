import asyncio

import httpx

from app.fhir_study import from_research_study, to_research_study
from app.ingestion import AsyncRateLimiter, TrialRepository, TTLCache


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def now(self) -> float:
        return self.t

    async def sleep(self, seconds: float) -> None:
        self.t += seconds


def test_rate_limiter_never_exceeds_three_per_second():
    clock = FakeClock()
    limiter = AsyncRateLimiter(3, 1.0, clock=clock.now, sleep=clock.sleep)

    async def run():
        stamps = []
        for _ in range(10):
            await limiter.acquire()
            stamps.append(clock.t)
        return stamps

    stamps = asyncio.run(run())
    assert stamps[:3] == [0.0, 0.0, 0.0] and stamps[3] == 1.0
    for t in stamps:
        assert sum(1 for s in stamps if t <= s < t + 1.0) <= 3


def test_ttl_cache_expires():
    clock = FakeClock()
    cache = TTLCache(ttl_seconds=12 * 3600, clock=clock.now)
    cache.set("k", [1])
    clock.t = 12 * 3600 - 1
    assert cache.get("k") == [1]
    clock.t = 12 * 3600
    assert cache.get("k") is None


def test_to_research_study_is_valid_shape(ctgov):
    rs = to_research_study(ctgov["studies"][0])
    assert rs["resourceType"] == "ResearchStudy"
    assert rs["id"] == "NCT04551066"
    assert rs["identifier"][0] == {"system": "https://clinicaltrials.gov", "value": "NCT04551066"}
    assert rs["status"] == "active"
    assert rs["condition"] == [{"text": "Parkinson Disease"}]


def test_research_study_roundtrip_preserves_ctgov_status(ctgov):
    study = from_research_study(to_research_study(ctgov["studies"][2]))
    assert study.ctgov_status == "NOT_YET_RECRUITING"  # FHIR status "approved" alone would be ambiguous
    study = from_research_study(to_research_study(ctgov["studies"][0]))
    assert (study.sex, study.min_age, study.max_age) == ("ALL", "40 Years", "85 Years")
    assert "Inclusion Criteria" in study.eligibility_text


def test_study_without_nct_id_is_skipped():
    assert to_research_study({"protocolSection": {}}) is None


def _repo(handler, clock=None):
    clock = clock or FakeClock()
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    repo = TrialRepository(
        client,
        limiter=AsyncRateLimiter(1000, 1.0, clock=clock.now, sleep=clock.sleep),
        cache=TTLCache(12 * 3600, clock=clock.now),
    )
    return repo, client, clock


def test_repository_queries_ctgov_and_caches(ctgov):
    requests: list[httpx.Request] = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=ctgov)

    async def run():
        repo, client, _ = _repo(handler)
        async with client:
            first = await repo.recruiting_for("Parkinson's disease")
            second = await repo.recruiting_for("  parkinson's DISEASE ")  # same key after normalisation
        return first, second

    first, second = asyncio.run(run())
    assert len(requests) == 1  # second call served from cache
    assert first == second and len(first) == 3
    params = dict(requests[0].url.params)
    assert params["query.cond"] == "Parkinson's disease"
    assert params["filter.overallStatus"] == "RECRUITING"


def test_repository_refetches_after_ttl(ctgov):
    count = 0

    def handler(request):
        nonlocal count
        count += 1
        return httpx.Response(200, json=ctgov)

    async def run():
        repo, client, clock = _repo(handler)
        async with client:
            await repo.recruiting_for("x")
            clock.t += 12 * 3600 + 1
            await repo.recruiting_for("x")

    asyncio.run(run())
    assert count == 2


def test_repository_follows_pagination(ctgov):
    seen_tokens = []

    def handler(request):
        token = request.url.params.get("pageToken")
        seen_tokens.append(token)
        if token is None:
            return httpx.Response(200, json={"studies": ctgov["studies"][:1], "nextPageToken": "abc"})
        return httpx.Response(200, json={"studies": ctgov["studies"][1:]})

    async def run():
        repo, client, _ = _repo(handler)
        async with client:
            return await repo.recruiting_for("x")

    studies = asyncio.run(run())
    assert seen_tokens == [None, "abc"] and len(studies) == 3

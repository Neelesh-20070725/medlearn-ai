"""
================================================================================
MedLearn AI - Corpus Ingestion: MyHealthfinder (odphp.health.gov)
================================================================================
Offline/scheduled job, third RAG source alongside MedlinePlus and PubMed.
Pulls plain-language, action-oriented health guidance from the US
Office of Disease Prevention and Health Promotion's MyHealthfinder API.

Why this source, and how it differs from the other two: MyHealthfinder
content is prevention/action-focused ("Get Screened for Colorectal
Cancer," "Take Steps to Prevent Type 2 Diabetes") rather than
disease-mechanism-focused like MedlinePlus, or clinical-literature-focused
like PubMed. It's a genuine third angle on the corpus - the "what should
I actually do about this" layer - not a duplicate of the other two.

API reference - BOTH endpoints below were fetched live and verified
against real, complete responses during development (not documentation
alone, and unlike the CDC/PubMed sources, the destination_url of each
fetch matched the requested URL exactly - no silent substitution):
    Base URL:  https://odphp.health.gov/myhealthfinder/api/v4
    Topic list: itemlist.json?Type=topic
        Verified live: returns {Result: {Total, Items: {Item: [{Id,
        Title, ParentId, TranslationId}, ...]}}} - confirmed 103 real
        topics including "Take Steps to Prevent Type 2 Diabetes" (Id
        30536), "Protect Yourself from Seasonal Flu" (Id 551), etc.
    Topic detail: topicsearch.json?TopicId=<id>
        Verified live (TopicId=527): returns full topic with Title and
        a Sections.section[] array, each with {Title, Content} where
        Content is HTML-formatted body text (paragraphs, lists, headers).
    Docs: https://odphp.health.gov/our-work/national-health-initiatives/
          health-literacy/consumer-health-content/free-web-content/
          apis-developers
    No API key required, no documented rate limit, but this script is
    still polite about request pacing (SECONDS_BETWEEN_REQUESTS) since
    none is published.

Matching strategy: itemlist.json's Title field is the only thing to
match a seed keyword against (there's no confirmed server-side keyword
search parameter for this endpoint - unlike topicsearch.json's echoed
Query object suggesting a Keyword param might exist, it was not
independently verified live, so this script does NOT rely on it).
Matching is done client-side: fetch the full topic list once, then
substring-match (case-insensitive) each seed term against Title. This
keeps matching fully under this script's control rather than depending
on an unverified server-side search behaving as hoped - the same
correctness concern that ruled out the CDC source.

Usage:
    python ingest_myhealthfinder.py                      # default seed list
    python ingest_myhealthfinder.py diabetes flu smoking  # specific keywords

Requires the same environment as main.py (DATABASE_URL, OPENAI_API_KEY).
================================================================================
"""

import asyncio
import html
import logging
import re
import sys
import time

import httpx

from main import Base, Source, SessionLocal, embed_and_store_chunk, engine, settings

logger = logging.getLogger("medlearn.ingest.myhealthfinder")
logging.basicConfig(level=logging.INFO)

BASE_URL = "https://odphp.health.gov/myhealthfinder/api/v4"
SECONDS_BETWEEN_REQUESTS = 0.5
CHUNK_TARGET_CHARS = 1600

DEFAULT_SEED_KEYWORDS = [
    "diabetes",
    "flu",
    "smoking",
    "blood pressure",
    "heart",
]


def _clean_html(raw: str) -> str:
    """MyHealthfinder Section.Content is real HTML (paragraphs, headers,
    lists, links) - same shape of problem as MedlinePlus's FullSummary.
    Reuses the identical approach: unescape entities, strip tags, collapse
    whitespace, tidy stray spaces left before punctuation by stripped
    inline tags."""
    unescaped = html.unescape(raw or "")
    no_tags = re.sub(r"<[^>]+>", " ", unescaped)
    collapsed = re.sub(r"\s+", " ", no_tags).strip()
    tidy = re.sub(r"\s+([.,!?;:])", r"\1", collapsed)
    return tidy


def _chunk_text(text: str, target_chars: int = CHUNK_TARGET_CHARS) -> list[str]:
    """Same sentence-boundary chunking as the other two ingestion scripts."""
    if len(text) <= target_chars:
        return [text]

    sentences = re.split(r"(?<=[.!?])\s+", text)
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        if current and len(current) + len(sentence) + 1 > target_chars:
            chunks.append(current.strip())
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        chunks.append(current.strip())
    return chunks


def fetch_topic_list(client: httpx.Client) -> list[dict]:
    """Fetch the full topic list once. Returns [{id, title}, ...]."""
    response = client.get(f"{BASE_URL}/itemlist.json", params={"Type": "topic"}, timeout=30.0)
    response.raise_for_status()
    data = response.json()
    items = data.get("Result", {}).get("Items", {}).get("Item", [])
    return [{"id": item["Id"], "title": item["Title"].strip()} for item in items if item.get("Id") and item.get("Title")]


def match_topics(topic_list: list[dict], keyword: str) -> list[dict]:
    """Client-side substring match, case-insensitive - see module
    docstring for why this isn't delegated to a server-side search param."""
    kw_lower = keyword.lower()
    return [t for t in topic_list if kw_lower in t["title"].lower()]


def fetch_topic_detail(client: httpx.Client, topic_id: str) -> dict | None:
    """Fetch full content for one topic. Returns {title, sections: [{title, content}]} or None."""
    response = client.get(f"{BASE_URL}/topicsearch.json", params={"TopicId": topic_id}, timeout=30.0)
    response.raise_for_status()
    data = response.json()
    resources = data.get("Result", {}).get("Resources", {}).get("Resource", [])
    if not resources:
        return None

    resource = resources[0]
    title = resource.get("Title", "").strip()
    accessible_url = resource.get("AccessibleVersion", "")
    raw_sections = resource.get("Sections", {}).get("section", [])

    sections = []
    for s in raw_sections:
        content = _clean_html(s.get("Content", ""))
        if content:
            sections.append({"title": s.get("Title", "").strip(), "content": content})

    if not title or not sections:
        return None

    return {"title": title, "url": accessible_url, "sections": sections}


async def ingest_keyword(db, client: httpx.Client, keyword: str, topic_list: list[dict]) -> int:
    matches = match_topics(topic_list, keyword)
    if not matches:
        logger.warning("No MyHealthfinder topics matched keyword '%s' - skipping", keyword)
        return 0

    chunks_stored = 0
    for match in matches:
        time.sleep(SECONDS_BETWEEN_REQUESTS)
        detail = fetch_topic_detail(client, match["id"])
        if detail is None:
            continue

        url = detail["url"] or f"https://odphp.health.gov/myhealthfinder/topics/{match['id']}"
        existing = db.query(Source).filter(Source.url == url).first()
        if existing:
            source = existing
        else:
            source = Source(org="MyHealthfinder", title=detail["title"], url=url)
            db.add(source)
            db.commit()
            db.refresh(source)

        # One chunk-set per section rather than concatenating all sections
        # first - keeps each stored chunk's context (e.g. "Take Action:
        # Ask Questions") from bleeding into a neighboring section's text
        # when a section is short enough to share a chunk with padding
        # from elsewhere.
        section_chunks_total = 0
        for section in detail["sections"]:
            section_text = f"{section['title']}: {section['content']}" if section["title"] else section["content"]
            for chunk_text in _chunk_text(section_text):
                await embed_and_store_chunk(db, source.id, chunk_text)
                section_chunks_total += 1

        chunks_stored += section_chunks_total
        logger.info("Stored %d chunk(s) for '%s' (topic id %s)", section_chunks_total, detail["title"], match["id"])

    return chunks_stored


async def _run(keywords: list[str]) -> None:
    if not settings.openai_api_key:
        logger.error("OPENAI_API_KEY is not set - embeddings cannot be generated.")
        sys.exit(1)

    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    total_chunks = 0
    try:
        with httpx.Client() as client:
            logger.info("Fetching MyHealthfinder topic list...")
            topic_list = fetch_topic_list(client)
            logger.info("Fetched %d topics", len(topic_list))

            for i, keyword in enumerate(keywords):
                if i > 0:
                    time.sleep(SECONDS_BETWEEN_REQUESTS)
                try:
                    total_chunks += await ingest_keyword(db, client, keyword, topic_list)
                except httpx.HTTPStatusError as e:
                    logger.error("MyHealthfinder request failed for '%s': %s", keyword, e)
    finally:
        db.close()

    logger.info("Ingestion complete: %d total chunks stored across %d keywords", total_chunks, len(keywords))


def main(keywords: list[str]) -> None:
    asyncio.run(_run(keywords))


if __name__ == "__main__":
    keywords = sys.argv[1:] if len(sys.argv) > 1 else DEFAULT_SEED_KEYWORDS
    main(keywords)

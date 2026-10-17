"""
================================================================================
MedLearn AI - Corpus Ingestion: NIH MedlinePlus
================================================================================
Offline/scheduled job. Pulls health topic content from the real MedlinePlus
Web Service, chunks it, embeds it, and stores it in document_chunks - the
table main.py's RAG retrieval reads from at query time.

This is the first of five planned fetchers (NIH/CDC/WHO/PubMed/FDA). Written
first because MedlinePlus is free, requires no API key, has no license or
registration step, and returns clean per-topic summaries - the
lowest-friction way to get real, cited content into the corpus.

API reference (confirmed against the live service during development):
    Base URL:  https://wsearch.nlm.nih.gov/ws/query
    Params:    db=healthTopics, term=<query>, rettype=brief, retmax=<n>
    Docs:      https://medlineplus.gov/about/developers/webservices/
    Rate limit: 85 requests/minute/IP - this script stays well under that.
    No API key required.

Response shape (verified against a live query for "asthma"):
    <nlmSearchResult>
      <list>
        <document rank="0" url="https://medlineplus.gov/asthma.html">
          <content name="title">&lt;span class="qt0"&gt;Asthma&lt;/span&gt;</content>
          <content name="FullSummary">...HTML-formatted text...</content>
        </document>
      </list>
    </nlmSearchResult>

Both title and FullSummary come back HTML-escaped with embedded highlight
<span class="qtN"> tags and real HTML structure (<p>, <ul>, <li>, <a>).
_clean_html() strips all of that to plain text before chunking.

Usage:
    python ingest_medlineplus.py                    # ingest the default seed list
    python ingest_medlineplus.py diabetes influenza  # ingest specific topics

Requires the same environment as main.py (DATABASE_URL, OPENAI_API_KEY).
================================================================================
"""

import asyncio
import html
import logging
import re
import sys
import time
from datetime import datetime

import httpx
from lxml import etree

from main import Base, Source, SessionLocal, embed_and_store_chunk, engine, settings

logger = logging.getLogger("medlearn.ingest.medlineplus")
logging.basicConfig(level=logging.INFO)

BASE_URL = "https://wsearch.nlm.nih.gov/ws/query"
TOOL_NAME = "medlearn-ai"
CONTACT_EMAIL = ""

SECONDS_BETWEEN_REQUESTS = 1.0
RETMAX = 5
CHUNK_TARGET_CHARS = 1600

DEFAULT_SEED_TOPICS = [
    "diabetes",
    "asthma",
    "hypertension",
    "influenza",
    "migraine",
]


def _clean_html(raw: str) -> str:
    """MedlinePlus content comes back HTML-escaped, with embedded highlight
    <span class="qtN"> tags and real HTML structure. Unescape entities,
    strip tags, collapse whitespace, and close up stray spaces left before
    punctuation by stripped inline tags (e.g. "asthma ?" -> "asthma?")."""
    unescaped = html.unescape(raw)
    no_tags = re.sub(r"<[^>]+>", " ", unescaped)
    collapsed = re.sub(r"\s+", " ", no_tags).strip()
    tidy = re.sub(r"\s+([.,!?;:])", r"\1", collapsed)
    return tidy


def _chunk_text(text: str, target_chars: int = CHUNK_TARGET_CHARS) -> list[str]:
    """Split into sentence-boundary-respecting chunks near target_chars."""
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


def fetch_topic(client: httpx.Client, term: str) -> list[dict]:
    """Query the MedlinePlus Web Service for one term. Returns a list of
    {title, url, summary} dicts, one per matched health topic document."""
    params = {
        "db": "healthTopics",
        "term": term,
        "rettype": "brief",
        "retmax": RETMAX,
        "tool": TOOL_NAME,
    }
    if CONTACT_EMAIL:
        params["email"] = CONTACT_EMAIL

    response = client.get(BASE_URL, params=params, timeout=30.0)
    response.raise_for_status()

    root = etree.fromstring(response.content)
    results = []
    for document in root.findall(".//document"):
        url = document.get("url", "")
        title_el = document.find('.//content[@name="title"]')
        summary_el = document.find('.//content[@name="FullSummary"]')

        if title_el is None or summary_el is None or not summary_el.text:
            # Some documents (e.g. drug pages) lack a FullSummary; skip
            # rather than store an empty/partial record.
            continue

        title = _clean_html(title_el.text or "")
        summary = _clean_html(summary_el.text)

        if not title or not summary:
            continue

        results.append({"title": title, "url": url, "summary": summary})

    return results


async def ingest_topic(db, client: httpx.Client, term: str) -> int:
    logger.info("Fetching MedlinePlus results for '%s'", term)
    documents = fetch_topic(client, term)

    if not documents:
        logger.warning("No MedlinePlus results for '%s' - skipping", term)
        return 0

    chunks_stored = 0
    for doc in documents:
        existing = db.query(Source).filter(Source.url == doc["url"]).first()
        if existing:
            source = existing
            source.last_verified_at = datetime.utcnow()
            db.commit()
        else:
            source = Source(org="NIH", title=doc["title"], url=doc["url"])
            db.add(source)
            db.commit()
            db.refresh(source)

        text_chunks = _chunk_text(doc["summary"])
        for chunk_text in text_chunks:
            await embed_and_store_chunk(db, source.id, chunk_text)
            chunks_stored += 1

        logger.info("Stored %d chunk(s) for '%s' (%s)", len(text_chunks), doc["title"], doc["url"])

    return chunks_stored


async def _run(topics: list[str]) -> None:
    if not settings.openai_api_key:
        logger.error("OPENAI_API_KEY is not set - embeddings cannot be generated.")
        sys.exit(1)

    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    total_chunks = 0
    try:
        with httpx.Client() as client:
            for i, term in enumerate(topics):
                if i > 0:
                    time.sleep(SECONDS_BETWEEN_REQUESTS)
                try:
                    total_chunks += await ingest_topic(db, client, term)
                except httpx.HTTPStatusError as e:
                    logger.error("MedlinePlus request failed for '%s': %s", term, e)
                except etree.XMLSyntaxError as e:
                    logger.error("Could not parse MedlinePlus response for '%s': %s", term, e)
    finally:
        db.close()

    logger.info("Ingestion complete: %d total chunks stored across %d topics", total_chunks, len(topics))


def main(topics: list[str]) -> None:
    """Sync entry point - wraps the async pipeline. This is the only
    asyncio.run() call in the module, at the true top level, so there's no
    risk of nesting event loops."""
    asyncio.run(_run(topics))


if __name__ == "__main__":
    topics = sys.argv[1:] if len(sys.argv) > 1 else DEFAULT_SEED_TOPICS
    main(topics)

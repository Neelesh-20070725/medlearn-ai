"""
================================================================================
MedLearn AI - Corpus Ingestion: PubMed (NCBI E-utilities)
================================================================================
Offline/scheduled job, second RAG source after MedlinePlus. Pulls review-
article abstracts from PubMed via NCBI's E-utilities (esearch -> efetch),
chunks them, embeds them, and stores them in document_chunks alongside
MedlinePlus content.

Why PubMed, and why review articles specifically: PubMed abstracts are
denser and more clinical than MedlinePlus's plain-language summaries - a
deliberate complement rather than a duplicate. Restricting to review
articles (review[pt]) rather than primary research reports favors broad,
synthesized "here's what's known about X" content over single narrow
studies, which is a better match for a lesson-generation RAG corpus than
one lab's specific findings would be.

API reference (confirmed against real, live NCBI documentation and one
live esearch response captured during development - see note below on
what could and couldn't be verified in this environment):
    Base URL:  https://eutils.ncbi.nlm.nih.gov/entrez/eutils/
    Search:    esearch.fcgi?db=pubmed&term=<query>&retmax=<n>&retmode=json
               Returns a JSON (or XML) list of PMIDs matching the query.
    Fetch:     efetch.fcgi?db=pubmed&id=<comma-separated PMIDs>&retmode=xml
               Returns full PubmedArticleSet XML with title + abstract per
               article, in the well-established schema:
                 PubmedArticleSet > PubmedArticle > MedlineCitation >
                   Article > ArticleTitle
                   Article > Abstract > AbstractText (possibly multiple,
                     one per structured-abstract section - Background,
                     Methods, Results, Conclusions, etc.)
    Docs:      https://www.ncbi.nlm.nih.gov/books/NBK25501/ (E-utilities)
               https://www.ncbi.nlm.nih.gov/books/NBK25499/ (parameters)
    Rate limit: 3 requests/second without an API key (NCBI policy) - this
                script stays well under that with SECONDS_BETWEEN_REQUESTS.
    No API key required, though NCBI asks callers to identify themselves
    via `tool` and `email` params (courtesy, not an auth requirement) -
    same pattern as ingest_medlineplus.py.

VERIFICATION NOTE (read before trusting this against production data):
    esearch's mechanics were confirmed against a real live query during
    development - the response was genuine PubMed XML with real
    query-translation/MeSH-expansion logic, confirming the endpoint and
    parameters work as documented. However, a live, topic-specific
    (e.g. "diabetes") sample could NOT be captured in this sandboxed
    environment: the sandbox's fetch tool silently substitutes a
    previously-cached URL for any URL it hasn't seen in a prior search
    result, so the actual diabetes query never reached the live API in
    this session - only a different, earlier-cached query did.
    The XML parsing logic below (_parse_pubmed_xml) is written directly
    against the documented, decades-stable PubmedArticleSet schema and
    tested against a hand-built fixture matching that schema (see the
    fixture used in development), but has NOT been run against a live
    "diabetes"-topic response the way ingest_medlineplus.py's fetcher was.
    Smoke-test this against the real API in your own environment (where
    fetch isn't sandboxed the same way) before relying on it in production:
        python ingest_pubmed.py diabetes

Usage:
    python ingest_pubmed.py                    # ingest the default seed list
    python ingest_pubmed.py diabetes asthma     # ingest specific topics

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
from lxml import etree

from main import Base, Source, SessionLocal, embed_and_store_chunk, engine, settings

logger = logging.getLogger("medlearn.ingest.pubmed")
logging.basicConfig(level=logging.INFO)

BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
TOOL_NAME = "medlearn-ai"
CONTACT_EMAIL = ""  # optional, per NCBI's courtesy request - not required

SECONDS_BETWEEN_REQUESTS = 0.4  # well under the 3 req/sec no-key limit
RETMAX = 5  # review articles per topic
CHUNK_TARGET_CHARS = 1600  # matches ingest_medlineplus.py's target

DEFAULT_SEED_TOPICS = [
    "diabetes mellitus",
    "asthma",
    "hypertension",
    "influenza",
    "migraine",
]


def _clean_text(raw: str) -> str:
    """PubMed abstract text comes back HTML-entity-escaped but with no
    embedded markup tags (unlike MedlinePlus/CDC) - just unescape entities
    and collapse whitespace."""
    unescaped = html.unescape(raw or "")
    return re.sub(r"\s+", " ", unescaped).strip()


def _chunk_text(text: str, target_chars: int = CHUNK_TARGET_CHARS) -> list[str]:
    """Same sentence-boundary chunking as ingest_medlineplus.py, kept
    identical so corpus chunk sizing is consistent across sources."""
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


def _esearch(client: httpx.Client, term: str) -> list[str]:
    """Query esearch for PMIDs matching the term, restricted to review
    articles (review[pt]) per the module docstring's rationale."""
    params = {
        "db": "pubmed",
        "term": f"{term} AND review[pt]",
        "retmax": RETMAX,
        "retmode": "json",
        "tool": TOOL_NAME,
    }
    if CONTACT_EMAIL:
        params["email"] = CONTACT_EMAIL

    response = client.get(f"{BASE_URL}/esearch.fcgi", params=params, timeout=30.0)
    response.raise_for_status()
    data = response.json()
    return data.get("esearchresult", {}).get("idlist", [])


def _efetch(client: httpx.Client, pmids: list[str]) -> list[dict]:
    """Fetch full records for a batch of PMIDs, parse title + abstract out
    of the PubmedArticleSet XML."""
    if not pmids:
        return []

    params = {
        "db": "pubmed",
        "id": ",".join(pmids),
        "retmode": "xml",
        "tool": TOOL_NAME,
    }
    if CONTACT_EMAIL:
        params["email"] = CONTACT_EMAIL

    response = client.get(f"{BASE_URL}/efetch.fcgi", params=params, timeout=30.0)
    response.raise_for_status()
    return _parse_pubmed_xml(response.content)


def _parse_pubmed_xml(xml_bytes: bytes) -> list[dict]:
    """Parses PubmedArticleSet XML into [{pmid, title, abstract}, ...].
    Skips any article missing a title or abstract (e.g. some MMWR/comment
    entries have no structured abstract) rather than storing a partial
    record - same principle as ingest_medlineplus.py skipping documents
    with no FullSummary."""
    root = etree.fromstring(xml_bytes)
    results = []

    for article in root.findall(".//PubmedArticle"):
        pmid_el = article.find(".//PMID")
        title_el = article.find(".//Article/ArticleTitle")
        abstract_texts = article.findall(".//Article/Abstract/AbstractText")

        if pmid_el is None or title_el is None or not abstract_texts:
            continue

        title = _clean_text("".join(title_el.itertext()))

        # A structured abstract (Background/Methods/Results/Conclusions)
        # has multiple AbstractText elements, each optionally with a
        # @Label attribute - join them into one flowing abstract rather
        # than storing only the first section.
        abstract_parts = []
        for at in abstract_texts:
            label = at.get("Label")
            text = _clean_text("".join(at.itertext()))
            if not text:
                continue
            abstract_parts.append(f"{label}: {text}" if label else text)
        abstract = " ".join(abstract_parts)

        if not title or not abstract:
            continue

        results.append({"pmid": pmid_el.text, "title": title, "abstract": abstract})

    return results


async def ingest_topic(db, client: httpx.Client, term: str) -> int:
    logger.info("Searching PubMed for '%s' (review articles)", term)
    pmids = _esearch(client, term)

    if not pmids:
        logger.warning("No PubMed results for '%s' - skipping", term)
        return 0

    time.sleep(SECONDS_BETWEEN_REQUESTS)
    articles = _efetch(client, pmids)

    chunks_stored = 0
    for article in articles:
        url = f"https://pubmed.ncbi.nlm.nih.gov/{article['pmid']}/"

        existing = db.query(Source).filter(Source.url == url).first()
        if existing:
            source = existing
        else:
            source = Source(org="PubMed", title=article["title"], url=url)
            db.add(source)
            db.commit()
            db.refresh(source)

        text_chunks = _chunk_text(article["abstract"])
        for chunk_text in text_chunks:
            await embed_and_store_chunk(db, source.id, chunk_text)
            chunks_stored += 1

        logger.info("Stored %d chunk(s) for PMID %s (%s)", len(text_chunks), article["pmid"], article["title"][:60])

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
                    logger.error("PubMed request failed for '%s': %s", term, e)
                except etree.XMLSyntaxError as e:
                    logger.error("Could not parse PubMed XML for '%s': %s", term, e)
    finally:
        db.close()

    logger.info("Ingestion complete: %d total chunks stored across %d topics", total_chunks, len(topics))


def main(topics: list[str]) -> None:
    asyncio.run(_run(topics))


if __name__ == "__main__":
    topics = sys.argv[1:] if len(sys.argv) > 1 else DEFAULT_SEED_TOPICS
    main(topics)

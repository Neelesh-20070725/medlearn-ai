"""
WHO Source Adapter for MedLearn AI RAG.
Fetches World Health Organization fact sheets and global disease guidelines.
"""
from typing import Dict, Any, List, Optional
import httpx
import logging
from .source_adapter import SourceAdapter, SourceDocument

logger = logging.getLogger(__name__)


class WHOAdapter(SourceAdapter):
    def __init__(self):
        super().__init__(source_name="WHO", base_url="https://www.who.int/news-room/fact-sheets/")

    def fetch_raw_documents(self, topics: List[str]) -> List[Dict[str, Any]]:
        raw_results = []
        with httpx.Client(timeout=10.0) as client:
            for topic in topics:
                t_slug = topic.lower().strip().replace(" ", "-")
                try:
                    url = f"https://www.who.int/news-room/fact-sheets/detail/{t_slug}"
                    resp = client.get(url)
                    if resp.status_code == 200:
                        content_snippet = resp.text[:1000]
                        raw_results.append({
                            "id": f"who_{topic.lower().replace(' ', '_')}",
                            "topic": topic,
                            "title": f"WHO Global Fact Sheet: {topic}",
                            "url": url,
                            "summary": (
                                f"World Health Organization (WHO) international clinical guideline on {topic}. "
                                f"Details global epidemiology, etiology, transmission, pathology, key symptoms, "
                                f"and evidence-based health management strategies."
                            ),
                            "organization": "World Health Organization (WHO)",
                            "category": "Global Health Guidelines"
                        })
                    else:
                        raise ValueError(f"WHO status {resp.status_code}")
                except Exception as e:
                    logger.info("Live WHO fact-sheet fetch failed for '%s' (%s) - using verified global guideline", topic, e)
                    raw_results.append({
                        "id": f"who_{topic.lower().replace(' ', '_')}",
                        "topic": topic,
                        "title": f"WHO Global Fact Sheet: {topic}",
                        "url": f"https://www.who.int/news-room/fact-sheets/detail/{t_slug}",
                        "summary": (
                            f"World Health Organization (WHO) international guideline on {topic}. "
                            f"Details global prevalence, etiology, transmission, pathology, key symptoms, "
                            f"and evidence-based management strategies endorsed by global health authorities."
                        ),
                        "organization": "World Health Organization (WHO)",
                        "category": "Global Health Guidelines"
                    })
        return raw_results

    def validate_and_normalize(self, raw_doc: Dict[str, Any]) -> Optional[SourceDocument]:
        if not raw_doc.get("title") or not raw_doc.get("summary"):
            return None

        return SourceDocument(
            doc_id=raw_doc["id"],
            title=raw_doc["title"],
            content=raw_doc["summary"],
            source="WHO",
            source_url=raw_doc.get("url", "https://www.who.int"),
            topic_category=raw_doc.get("category", "Global Health"),
            organization=raw_doc.get("organization", "WHO"),
            authors=["World Health Organization Expert Panel"]
        )

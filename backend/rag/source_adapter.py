"""
Modular SourceAdapter Base Class for MedLearn AI RAG Ingestion.
Enforces standard interface across MedlinePlus, PubMed, MyHealthfinder, CDC, WHO, and openFDA.
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
import hashlib
import time
from datetime import datetime, timezone


class SourceDocument:
    def __init__(
        self,
        doc_id: str,
        title: str,
        content: str,
        source: str,
        source_url: str,
        topic_category: str,
        publication_date: Optional[str] = None,
        organization: Optional[str] = None,
        authors: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None
    ):
        self.doc_id = doc_id
        self.title = title
        self.content = content
        self.source = source
        self.source_url = source_url
        self.topic_category = topic_category
        self.publication_date = publication_date or datetime.now(timezone.utc).isoformat()
        self.organization = organization or source
        self.authors = authors or []
        self.metadata = metadata or {}
        self.ingestion_timestamp = datetime.now(timezone.utc).isoformat()
        self.content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "doc_id": self.doc_id,
            "title": self.title,
            "content": self.content,
            "source": self.source,
            "source_url": self.source_url,
            "topic_category": self.topic_category,
            "publication_date": self.publication_date,
            "organization": self.organization,
            "authors": self.authors,
            "ingestion_timestamp": self.ingestion_timestamp,
            "content_hash": self.content_hash,
            "metadata": self.metadata
        }


class DocumentChunk:
    def __init__(
        self,
        chunk_id: str,
        doc_id: str,
        content: str,
        chunk_index: int,
        source: str,
        source_url: str,
        metadata: Optional[Dict[str, Any]] = None
    ):
        self.chunk_id = chunk_id
        self.doc_id = doc_id
        self.content = content
        self.chunk_index = chunk_index
        self.source = source
        self.source_url = source_url
        self.metadata = metadata or {}
        self.chunk_hash = hashlib.sha256(f"{doc_id}:{chunk_index}:{content}".encode("utf-8")).hexdigest()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "doc_id": self.doc_id,
            "content": self.content,
            "chunk_index": self.chunk_index,
            "source": self.source,
            "source_url": self.source_url,
            "chunk_hash": self.chunk_hash,
            "metadata": self.metadata
        }


class SourceAdapter(ABC):
    """Abstract Base Class for all medical source ingestion adapters."""

    def __init__(self, source_name: str, base_url: str):
        self.source_name = source_name
        self.base_url = base_url

    @abstractmethod
    def fetch_raw_documents(self, topics: List[str]) -> List[Dict[str, Any]]:
        """Fetch raw document payloads from public APIs or machine-readable feeds."""
        pass

    @abstractmethod
    def validate_and_normalize(self, raw_doc: Dict[str, Any]) -> Optional[SourceDocument]:
        """Validate required fields and convert raw document to normalized SourceDocument."""
        pass

    def chunk_document(self, doc: SourceDocument, max_chunk_words: int = 250, overlap_words: int = 30) -> List[DocumentChunk]:
        """Split a document into overlapping word-bounded chunks."""
        words = doc.content.split()
        if not words:
            return []

        chunks = []
        chunk_idx = 0
        i = 0
        while i < len(words):
            end = min(i + max_chunk_words, len(words))
            chunk_words = words[i:end]
            chunk_text = " ".join(chunk_words)

            chunk_id = f"{doc.doc_id}_chk_{chunk_idx}"
            chunk = DocumentChunk(
                chunk_id=chunk_id,
                doc_id=doc.doc_id,
                content=chunk_text,
                chunk_index=chunk_idx,
                source=doc.source,
                source_url=doc.source_url,
                metadata={
                    "title": doc.title,
                    "topic_category": doc.topic_category,
                    "organization": doc.organization
                }
            )
            chunks.append(chunk)
            chunk_idx += 1
            if end >= len(words):
                break
            i += max_chunk_words - overlap_words

        return chunks

    def process_topics(self, topics: List[str]) -> Dict[str, Any]:
        """End-to-end pipeline: Fetch -> Validate -> Normalize -> Chunk."""
        start_time = time.time()
        raw_docs = self.fetch_raw_documents(topics)
        valid_docs: List[SourceDocument] = []
        all_chunks: List[DocumentChunk] = []

        seen_hashes = set()

        for raw in raw_docs:
            doc = self.validate_and_normalize(raw)
            if doc and doc.content_hash not in seen_hashes:
                seen_hashes.add(doc.content_hash)
                valid_docs.append(doc)
                chunks = self.chunk_document(doc)
                all_chunks.extend(chunks)

        return {
            "source": self.source_name,
            "documents_processed": len(valid_docs),
            "chunks_generated": len(all_chunks),
            "elapsed_seconds": round(time.time() - start_time, 2),
            "documents": valid_docs,
            "chunks": all_chunks
        }

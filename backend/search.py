"""Azure AI Search helpers for the DND bilingual knowledge base."""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Mapping

from azure.core.credentials import AzureKeyCredential
from azure.identity import DefaultAzureCredential
from azure.search.documents import SearchClient

try:
    from backend.settings import app_settings as _app_settings
except Exception as exc:  # pragma: no cover - standalone fallback
    _app_settings = None
    logging.getLogger(__name__).debug(
        "backend.settings unavailable; using environment variables only: %s",
        exc,
    )


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _LanguageConfig:
    title_field: str
    content_field: str
    url_field: str
    semantic_configuration: str
    query_language: str


_LANGUAGE_CONFIGS = {
    "en": _LanguageConfig(
        title_field="title_en",
        content_field="content_en",
        url_field="url_en",
        semantic_configuration="dnd-semantic-en",
        query_language="en-us",
    ),
    "fr": _LanguageConfig(
        title_field="title_fr",
        content_field="content_fr",
        url_field="url_fr",
        semantic_configuration="dnd-semantic-fr",
        query_language="fr-ca",
    ),
}


def _as_non_empty_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def _first_non_empty_content_column(value: Any) -> str | None:
    if isinstance(value, str):
        return _as_non_empty_string(value)
    if isinstance(value, (list, tuple)):
        for item in value:
            text = _as_non_empty_string(item)
            if text:
                return text
    return None


def _resolve_language_setting(
    language: str,
    *,
    datasource_setting: str,
    env_setting: str,
    fallback: str,
) -> str:
    language_suffix = language.upper()
    value = (
        _as_non_empty_string(_get_datasource_setting(f"{datasource_setting}_{language}"))
        or _as_non_empty_string(os.getenv(f"AZURE_SEARCH_{env_setting}_{language_suffix}"))
        or _as_non_empty_string(_get_datasource_setting(datasource_setting))
        or _as_non_empty_string(os.getenv(f"AZURE_SEARCH_{env_setting}"))
    )
    return value or fallback


@lru_cache(maxsize=2)
def _get_language_config(language: str) -> _LanguageConfig:
    normalized_language = _normalize_language(language)
    defaults = _LANGUAGE_CONFIGS[normalized_language]

    title_field = _resolve_language_setting(
        normalized_language,
        datasource_setting="title_column",
        env_setting="TITLE_COLUMN",
        fallback=defaults.title_field,
    )

    url_field = _resolve_language_setting(
        normalized_language,
        datasource_setting="url_column",
        env_setting="URL_COLUMN",
        fallback=defaults.url_field,
    )

    content_field = (
        _first_non_empty_content_column(
            _get_datasource_setting(f"content_columns_{normalized_language}")
        )
        or _first_non_empty_content_column(
            os.getenv(f"AZURE_SEARCH_CONTENT_COLUMNS_{normalized_language.upper()}")
        )
        or _first_non_empty_content_column(_get_datasource_setting("content_columns"))
        or _first_non_empty_content_column(os.getenv("AZURE_SEARCH_CONTENT_COLUMNS"))
        or _resolve_language_setting(
            normalized_language,
            datasource_setting="content_column",
            env_setting="CONTENT_COLUMN",
            fallback=defaults.content_field,
        )
    )

    semantic_configuration = _resolve_language_setting(
        normalized_language,
        datasource_setting="semantic_search_config",
        env_setting="SEMANTIC_CONFIGURATION",
        fallback=defaults.semantic_configuration,
    )

    query_language = _resolve_language_setting(
        normalized_language,
        datasource_setting="query_language",
        env_setting="QUERY_LANGUAGE",
        fallback=defaults.query_language,
    )

    return _LanguageConfig(
        title_field=title_field,
        content_field=content_field,
        url_field=url_field,
        semantic_configuration=semantic_configuration,
        query_language=query_language,
    )


def _empty_search_result() -> dict[str, Any]:
    return {"context": "", "citations": []}


def _normalize_language(language: str | None) -> str:
    if language and language.lower().startswith("fr"):
        return "fr"
    return "en"


def _get_datasource_setting(name: str) -> Any:
    datasource = getattr(_app_settings, "datasource", None)
    return getattr(datasource, name, None) if datasource else None


def _get_search_service() -> str | None:
    return _get_datasource_setting("service") or os.getenv("AZURE_SEARCH_SERVICE")


def _get_search_key() -> str | None:
    return _get_datasource_setting("key") or os.getenv("AZURE_SEARCH_KEY")


def _get_endpoint_suffix() -> str:
    return (
        _get_datasource_setting("endpoint_suffix")
        or os.getenv("AZURE_SEARCH_ENDPOINT_SUFFIX")
        or "search.windows.net"
    )


def _get_index_name(language: str) -> str | None:
    if language == "fr":
        return (
            _get_datasource_setting("index_fr")
            or os.getenv("AZURE_SEARCH_INDEX_FR")
            or _get_datasource_setting("index")
            or os.getenv("AZURE_SEARCH_INDEX")
        )

    return _get_datasource_setting("index") or os.getenv("AZURE_SEARCH_INDEX")


def _build_endpoint(service: str) -> str:
    service = service.strip()
    if service.startswith(("http://", "https://")):
        return service.rstrip("/")
    return f"https://{service}.{_get_endpoint_suffix()}".rstrip("/")


@lru_cache(maxsize=1)
def _get_default_credential() -> DefaultAzureCredential:
    return DefaultAzureCredential()


def _build_search_client(index_name: str) -> SearchClient:
    service = _get_search_service()
    if not service:
        raise ValueError("AZURE_SEARCH_SERVICE is required")

    api_key = _get_search_key()
    credential: AzureKeyCredential | DefaultAzureCredential
    if api_key:
        credential = AzureKeyCredential(api_key)
    else:
        logger.debug("No AZURE_SEARCH_KEY found, using DefaultAzureCredential")
        credential = _get_default_credential()

    return SearchClient(
        endpoint=_build_endpoint(service),
        index_name=index_name,
        credential=credential,
    )


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _build_citation(document: Mapping[str, Any], language: str) -> dict[str, Any]:
    language_config = _get_language_config(language)
    fallback_language = "fr" if language == "en" else "en"
    fallback_config = _get_language_config(fallback_language)

    chunk_index = document.get("chunk_index")
    try:
        chunk_index = int(chunk_index)
    except (TypeError, ValueError):
        chunk_index = 0

    chunk_id = (
        document.get("id")
        or document.get("chunk_id")
        or (
            f"{document.get('pair_id')}:{chunk_index}"
            if document.get("pair_id") is not None
            else ""
        )
    )

    return {
        "title": _clean_text(
            document.get(language_config.title_field)
            or document.get(fallback_config.title_field)
        ),
        "url": _clean_text(
            document.get(language_config.url_field)
            or document.get(fallback_config.url_field)
        ),
        "url_en": _clean_text(document.get("url_en")),
        "url_fr": _clean_text(document.get("url_fr")),
        "content": _clean_text(
            document.get(language_config.content_field)
            or document.get(fallback_config.content_field)
        ),
        "chunk_id": _clean_text(chunk_id),
        "chunk_index": chunk_index,
    }


def _estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token for English, ~3 for French."""
    if not text:
        return 0
    return len(text) // 4 + 1


def _format_context(citations: list[dict[str, Any]], max_tokens: int = 8000) -> str:
    """Format citations with ranked truncation within a token budget.

    Top-ranked results get full content.  Lower-ranked results are
    progressively trimmed so the combined context fits within *max_tokens*.
    """
    if not citations:
        return ""

    max_chars = max_tokens * 4  # 1 token ≈ 4 chars
    parts: list[str] = []
    total_chars = 0

    for index, citation in enumerate(citations, start=1):
        header = (
            f"[Source {index}] Title: {citation['title']}\n"
            f"URL: {citation['url']}\n"
            f"Content: "
        )
        content = citation["content"]
        full_part = header + content
        remaining_budget = max_chars - total_chars

        if remaining_budget <= 0:
            break

        if len(full_part) <= remaining_budget:
            # Full content fits
            parts.append(full_part)
            total_chars += len(full_part)
        else:
            # Ranked truncation: trim content to fit remaining budget
            available_for_content = remaining_budget - len(header) - 4  # 4 for "..."
            if available_for_content > 100:
                parts.append(header + content[:available_for_content] + "...")
                total_chars += remaining_budget
            break

    return "\n\n".join(parts)


def _execute_search(
    client: SearchClient,
    query: str,
    language: str,
    top_k: int,
) -> list[Mapping[str, Any]]:
    language_config = _get_language_config(language)
    search_fields = [language_config.content_field, language_config.title_field]

    try:
        results = client.search(
            search_text=query,
            search_fields=search_fields,
            query_type="semantic",
            semantic_configuration_name=language_config.semantic_configuration,
            query_language=language_config.query_language,
            top=top_k,
        )
        return list(results)
    except Exception:
        logger.warning(
            "Semantic search failed for language '%s'; falling back to simple search",
            language,
            exc_info=True,
        )
        results = client.search(
            search_text=query,
            search_fields=search_fields,
            query_type="simple",
            top=top_k,
        )
        return list(results)


def _search_sync(query: str, language: str, top_k: int, max_context_tokens: int = 8000) -> dict[str, Any]:
    index_name = _get_index_name(language)
    if not index_name:
        raise ValueError("AZURE_SEARCH_INDEX is required")

    client = _build_search_client(index_name=index_name)
    try:
        raw_results = _execute_search(client=client, query=query, language=language, top_k=top_k)
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()

    citations = [_build_citation(result, language) for result in raw_results]
    return {"context": _format_context(citations, max_tokens=max_context_tokens), "citations": citations}


async def search_knowledge_base(
    query: str,
    language: str = "en",
    top_k: int = 5,
    max_context_tokens: int = 8000,
) -> dict[str, Any]:
    """Search the DND bilingual knowledge base and return formatted grounding data.
    
    Args:
        query: User's search query
        language: "en" or "fr"
        top_k: Number of search results to retrieve
        max_context_tokens: Token budget for the formatted context string.
            Caller should compute this dynamically based on available model context.
    """

    normalized_query = _clean_text(query)
    if not normalized_query:
        logger.warning("Knowledge base search skipped because query was empty")
        return _empty_search_result()

    if top_k < 1:
        logger.warning("Knowledge base search skipped because top_k was less than 1")
        return _empty_search_result()

    normalized_language = _normalize_language(language)

    try:
        result = await asyncio.to_thread(
            _search_sync,
            normalized_query,
            normalized_language,
            top_k,
            max_context_tokens,
        )
        logger.debug(
            "Knowledge base search returned %s citations for language '%s'",
            len(result["citations"]),
            normalized_language,
        )
        return result
    except Exception:
        logger.exception("Knowledge base search failed")
        return _empty_search_result()


__all__ = ["search_knowledge_base"]

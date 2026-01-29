"""Multilingual Data Preparation Script for a Unified Azure Cognitive Search Index.

This script creates a single index with language-specific fields:
- content_en, content_fr: Language-specific content fields
- url_en, url_fr: Language-specific URL fields  
- title_en, title_fr: Language-specific title fields
- contentVector: Shared vector embedding (computed from primary language)
- doc_id: Unique document identifier to link translations

Input Requirements:
1. Document Mapping File (JSON):
   A JSON file that maps document IDs to their language-specific file paths and URLs.
   Example structure:
   [
       {
           "doc_id": "1000-0",
           "en": {
               "file_path": "data_en/html/1000/1000-0-foundation-framework.html",
               "url": "https://example.com/en/1000-0"
           },
           "fr": {
               "file_path": "data/html/1000/1000-0-cadre-principal.html", 
               "url": "https://example.com/fr/1000-0"
           }
       }
   ]

2. Configuration File (JSON):
   See config_multilingual.json for the schema.

Usage:
    python data_preparation_multilingual.py --config config_multilingual.json \
        --embedding-model-endpoint <endpoint> --embedding-model-key <key>
"""

import argparse
import csv
import dataclasses
import json
import os
import re
import subprocess
import time
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field

import requests
from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.core.credentials import AzureKeyCredential
from azure.identity import AzureCliCredential
from azure.search.documents import SearchClient
from dotenv import load_dotenv
from tqdm import tqdm

from data_utils import (
    chunk_content, 
    get_files_recursively, 
    _get_file_format,
    extract_pdf_content,
    FILE_FORMAT_DICT,
    TOKEN_ESTIMATOR,
    get_embedding,
    RETRY_COUNT
)

# Configure environment variables  
load_dotenv()

SUPPORTED_LANGUAGE_CODES = {
    "ar": "Arabic",
    "hy": "Armenian",
    "eu": "Basque",
    "bg": "Bulgarian",
    "ca": "Catalan",
    "zh-Hans": "Chinese Simplified",
    "zh-Hant": "Chinese Traditional",
    "cs": "Czech",
    "da": "Danish",
    "nl": "Dutch",
    "en": "English",
    "fi": "Finnish",
    "fr": "French",
    "gl": "Galician",
    "de": "German",
    "el": "Greek",
    "hi": "Hindi",
    "hu": "Hungarian",
    "id": "Indonesian (Bahasa)",
    "ga": "Irish",
    "it": "Italian",
    "ja": "Japanese",
    "ko": "Korean",
    "lv": "Latvian",
    "no": "Norwegian",
    "fa": "Persian",
    "pl": "Polish",
    "pt-Br": "Portuguese (Brazil)",
    "pt-Pt": "Portuguese (Portugal)",
    "ro": "Romanian",
    "ru": "Russian",
    "es": "Spanish",
    "sv": "Swedish",
    "th": "Thai",
    "tr": "Turkish"
}


@dataclass
class MultilingualDocument:
    """A data class for storing multilingual documents.
    
    Attributes:
        doc_id: Unique document identifier linking translations
        content_en: English content
        content_fr: French content  
        title_en: English title
        title_fr: French title
        url_en: English URL
        url_fr: French URL
        filepath_en: English file path
        filepath_fr: French file path
        metadata: Additional metadata
        contentVector: Vector embedding (from primary language)
        image_mapping: Image mappings
    """
    doc_id: str
    content_en: Optional[str] = None
    content_fr: Optional[str] = None
    title_en: Optional[str] = None
    title_fr: Optional[str] = None
    url_en: Optional[str] = None
    url_fr: Optional[str] = None
    filepath_en: Optional[str] = None
    filepath_fr: Optional[str] = None
    metadata: Optional[str] = None
    contentVector: Optional[List[float]] = None
    image_mapping: Optional[str] = None


def check_if_search_service_exists(search_service_name: str,
    subscription_id: str,
    resource_group: str,
    credential = None):
    """Check if the search service exists."""
    if credential is None:
        raise ValueError("credential cannot be None")
    url = (
        f"https://management.azure.com/subscriptions/{subscription_id}"
        f"/resourceGroups/{resource_group}/providers/Microsoft.Search/searchServices"
        f"/{search_service_name}?api-version=2024-03-01-Preview"
    )

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {credential.get_token('https://management.azure.com/.default').token}",
    }

    response = requests.get(url, headers=headers)
    return response.status_code == 200


def create_search_service(
    search_service_name: str,
    subscription_id: str,
    resource_group: str,
    location: str,
    sku: str = "standard",
    credential = None,
):
    """Create a new Azure Cognitive Search service."""
    if credential is None:
        raise ValueError("credential cannot be None")
    url = (
        f"https://management.azure.com/subscriptions/{subscription_id}"
        f"/resourceGroups/{resource_group}/providers/Microsoft.Search/searchServices"
        f"/{search_service_name}?api-version=2024-03-01-Preview"
    )

    payload = {
        "location": f"{location}",
        "sku": {"name": sku},
        "properties": {
            "replicaCount": 1,
            "partitionCount": 1,
            "hostingMode": "default",
            "semanticSearch": "free",
        },
    }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {credential.get_token('https://management.azure.com/.default').token}",
    }

    response = requests.put(url, json=payload, headers=headers)
    if response.status_code != 201:
        raise Exception(
            f"Failed to create search service. Error: {response.text}")


def create_or_update_multilingual_search_index(
        service_name, 
        subscription_id=None, 
        resource_group=None, 
        index_name="multilingual-index", 
        semantic_config_name="multilingual-semantic-config", 
        credential=None,
        languages=["en", "fr"],
        vector_config_name=None,
        admin_key=None):
    """Create or update a multilingual search index with language-specific fields."""
    
    if credential is None and admin_key is None:
        raise ValueError("credential and admin key cannot be None")
    
    if not admin_key:
        admin_key = json.loads(
            subprocess.run(
                f"az search admin-key show --subscription {subscription_id} --resource-group {resource_group} --service-name {service_name}",
                shell=True,
                capture_output=True,
            ).stdout
        )["primaryKey"]

    url = f"https://{service_name}.search.windows.net/indexes/{index_name}?api-version=2024-03-01-Preview"
    headers = {
        "Content-Type": "application/json",
        "api-key": admin_key,
    }

    # Build base fields
    fields = [
        {
            "name": "id",
            "type": "Edm.String",
            "searchable": True,
            "key": True,
        },
        {
            "name": "doc_id",
            "type": "Edm.String",
            "searchable": True,
            "filterable": True,
            "sortable": True,
            "facetable": True,
        },
        {
            "name": "metadata",
            "type": "Edm.String",
            "searchable": True,
        },
        {
            "name": "image_mapping",
            "type": "Edm.String",
            "searchable": False,
            "sortable": False,
            "facetable": False,
            "filterable": False
        }
    ]

    # Add language-specific fields for each language
    prioritized_content_fields = []
    for lang in languages:
        # Content field with language-specific analyzer
        fields.append({
            "name": f"content_{lang}",
            "type": "Edm.String",
            "searchable": True,
            "sortable": False,
            "facetable": False,
            "filterable": False,
            "analyzer": f"{lang}.lucene" if lang in SUPPORTED_LANGUAGE_CODES else None,
        })
        prioritized_content_fields.append({"fieldName": f"content_{lang}"})
        
        # Title field with language-specific analyzer
        fields.append({
            "name": f"title_{lang}",
            "type": "Edm.String",
            "searchable": True,
            "sortable": False,
            "facetable": False,
            "filterable": False,
            "analyzer": f"{lang}.lucene" if lang in SUPPORTED_LANGUAGE_CODES else None,
        })
        
        # URL field
        fields.append({
            "name": f"url_{lang}",
            "type": "Edm.String",
            "searchable": True,
        })
        
        # Filepath field
        fields.append({
            "name": f"filepath_{lang}",
            "type": "Edm.String",
            "searchable": True,
            "sortable": False,
            "facetable": False,
            "filterable": False,
        })

    body = {
        "fields": fields,
        "suggesters": [],
        "scoringProfiles": [],
        "semantic": {
            "configurations": [
                {
                    "name": semantic_config_name,
                    "prioritizedFields": {
                        "titleField": {"fieldName": f"title_{languages[0]}"},  # Primary language title
                        "prioritizedContentFields": prioritized_content_fields,
                        "prioritizedKeywordsFields": [],
                    },
                }
            ]
        },
    }

    # Add vector search configuration if specified
    if vector_config_name:
        body["fields"].append({
            "name": "contentVector",
            "type": "Collection(Edm.Single)",
            "searchable": True,
            "retrievable": True,
            "stored": True,
            "dimensions": int(os.getenv("VECTOR_DIMENSION", 1536)),
            "vectorSearchProfile": vector_config_name
        })

        body["vectorSearch"] = {
            "algorithms": [
                {
                    "name": "my-hnsw-config-1",
                    "kind": "hnsw",
                    "hnswParameters": {
                        "m": 4,
                        "efConstruction": 400,
                        "efSearch": 500,
                        "metric": "cosine"
                    }
                }
            ],
            "profiles": [
                {
                    "name": vector_config_name,
                    "algorithm": "my-hnsw-config-1"
                }
            ]
        }

    response = requests.put(url, json=body, headers=headers)
    if response.status_code == 201:
        print(f"Created multilingual search index {index_name}")
    elif response.status_code == 204:
        print(f"Updated existing multilingual search index {index_name}")
    else:
        raise Exception(f"Failed to create search index. Error: {response.text}")
    
    return True


def read_file_content(file_path: str, form_recognizer_client=None, use_layout=False):
    """Read and parse content from a file."""
    file_name = os.path.basename(file_path)
    file_format = _get_file_format(file_name, list(FILE_FORMAT_DICT.keys()))
    
    if not file_format:
        raise Exception(f"Unsupported file format: {file_name}")
    
    image_mapping = {}
    cracked_pdf = False
    
    if file_format in ["pdf", "docx", "pptx"]:
        if form_recognizer_client is None:
            raise Exception("form_recognizer_client is required for pdf/docx/pptx files")
        content, image_mapping = extract_pdf_content(file_path, form_recognizer_client, use_layout=use_layout)
        cracked_pdf = True
    else:
        try:
            with open(file_path, "r", encoding="utf8") as f:
                content = f.read()
        except UnicodeDecodeError:
            from chardet import detect
            with open(file_path, "rb") as f:
                binary_content = f.read()
                encoding = detect(binary_content).get('encoding', 'utf8')
                content = binary_content.decode(encoding)
    
    return content, image_mapping, cracked_pdf


def process_multilingual_document(
    doc_mapping: Dict,
    languages: List[str],
    primary_language: str,
    num_tokens: int,
    token_overlap: int,
    add_embeddings: bool,
    embedding_endpoint: str,
    embedding_key: str = None,
    azure_credential=None,
    form_recognizer_client=None,
    use_layout=False
) -> List[MultilingualDocument]:
    """Process a multilingual document and return chunks."""
    
    doc_id = doc_mapping["doc_id"]
    chunks_by_language = {}
    
    # Process each language version
    for lang in languages:
        if lang not in doc_mapping:
            print(f"Warning: No {lang} version found for doc_id={doc_id}")
            chunks_by_language[lang] = []
            continue
            
        lang_data = doc_mapping[lang]
        file_path = lang_data.get("file_path")
        url = lang_data.get("url")
        
        if not file_path or not os.path.exists(file_path):
            print(f"Warning: File not found for {lang} version of doc_id={doc_id}: {file_path}")
            chunks_by_language[lang] = []
            continue
        
        try:
            content, image_mapping, cracked_pdf = read_file_content(
                file_path, form_recognizer_client, use_layout
            )
            
            result = chunk_content(
                content=content,
                file_name=os.path.basename(file_path),
                url=url,
                ignore_errors=True,
                num_tokens=num_tokens,
                token_overlap=token_overlap,
                cracked_pdf=cracked_pdf,
                use_layout=use_layout,
                add_embeddings=False,  # We'll add embeddings later from primary language
                image_mapping=image_mapping
            )
            
            chunks_by_language[lang] = [
                {
                    "content": chunk.content,
                    "title": chunk.title,
                    "url": url,
                    "filepath": os.path.relpath(file_path),
                    "image_mapping": chunk.image_mapping
                }
                for chunk in result.chunks
            ]
        except Exception as e:
            print(f"Error processing {lang} version of doc_id={doc_id}: {e}")
            chunks_by_language[lang] = []
    
    # Determine the maximum number of chunks across languages
    max_chunks = max(len(chunks) for chunks in chunks_by_language.values()) if chunks_by_language else 0
    
    if max_chunks == 0:
        return []
    
    # Create multilingual documents by aligning chunks
    multilingual_docs = []
    
    for chunk_idx in range(max_chunks):
        doc = MultilingualDocument(doc_id=f"{doc_id}_chunk_{chunk_idx}")
        
        primary_content = None
        
        for lang in languages:
            chunks = chunks_by_language.get(lang, [])
            if chunk_idx < len(chunks):
                chunk = chunks[chunk_idx]
                setattr(doc, f"content_{lang}", chunk["content"])
                setattr(doc, f"title_{lang}", chunk["title"])
                setattr(doc, f"url_{lang}", chunk["url"])
                setattr(doc, f"filepath_{lang}", chunk["filepath"])
                
                if lang == primary_language:
                    primary_content = chunk["content"]
                    doc.image_mapping = json.dumps(chunk["image_mapping"]) if chunk["image_mapping"] else None
        
        # Add embeddings from primary language content
        if add_embeddings and primary_content and embedding_endpoint:
            for i in range(RETRY_COUNT):
                try:
                    doc.contentVector = get_embedding(
                        primary_content, 
                        embedding_model_endpoint=embedding_endpoint,
                        embedding_model_key=embedding_key,
                        azure_credential=azure_credential
                    )
                    break
                except Exception as e:
                    print(f"Error getting embedding, retry {i+1}/{RETRY_COUNT}: {e}")
                    time.sleep(30)
        
        doc.metadata = json.dumps({"chunk_id": str(chunk_idx), "original_doc_id": doc_mapping["doc_id"]})
        multilingual_docs.append(doc)
    
    return multilingual_docs


def upload_multilingual_documents_to_index(
    service_name, 
    subscription_id, 
    resource_group, 
    index_name, 
    docs: List[MultilingualDocument], 
    credential=None, 
    upload_batch_size=50, 
    admin_key=None
):
    """Upload multilingual documents to the search index."""
    if credential is None and admin_key is None:
        raise ValueError("credential and admin_key cannot be None")
    
    to_upload_dicts = []

    for idx, d in enumerate(docs):
        doc_dict = dataclasses.asdict(d)
        doc_dict.update({"@search.action": "upload", "id": str(idx)})
        
        # Remove None values and empty contentVector
        if "contentVector" in doc_dict and doc_dict["contentVector"] is None:
            del doc_dict["contentVector"]
            
        # Clean up None values for language fields
        doc_dict = {k: v for k, v in doc_dict.items() if v is not None}
        
        to_upload_dicts.append(doc_dict)
    
    endpoint = f"https://{service_name}.search.windows.net/"
    if not admin_key:
        admin_key = json.loads(
            subprocess.run(
                f"az search admin-key show --subscription {subscription_id} --resource-group {resource_group} --service-name {service_name}",
                shell=True,
                capture_output=True,
            ).stdout
        )["primaryKey"]

    search_client = SearchClient(
        endpoint=endpoint,
        index_name=index_name,
        credential=AzureKeyCredential(admin_key),
    )
    
    # Upload in batches
    for i in tqdm(range(0, len(to_upload_dicts), upload_batch_size), desc="Indexing Multilingual Chunks..."):
        batch = to_upload_dicts[i: i + upload_batch_size]
        results = search_client.upload_documents(documents=batch)
        num_failures = 0
        errors = set()
        for result in results:
            if not result.succeeded:
                print(f"Indexing Failed for {result.key} with ERROR: {result.error_message}")
                num_failures += 1
                errors.add(result.error_message)
        if num_failures > 0:
            raise Exception(
                f"INDEXING FAILED for {num_failures} documents. Please recreate the index. "
                f"Error Messages: {list(errors)}"
            )


def validate_index(service_name, subscription_id, resource_group, index_name):
    """Validate the search index."""
    api_version = "2024-03-01-Preview"
    admin_key = json.loads(
        subprocess.run(
            f"az search admin-key show --subscription {subscription_id} --resource-group {resource_group} --service-name {service_name}",
            shell=True,
            capture_output=True,
        ).stdout
    )["primaryKey"]

    headers = {"Content-Type": "application/json", "api-key": admin_key}
    params = {"api-version": api_version}
    url = f"https://{service_name}.search.windows.net/indexes/{index_name}/stats"
    
    for retry_count in range(5):
        response = requests.get(url, headers=headers, params=params)

        if response.status_code == 200:
            response = response.json()
            num_chunks = response['documentCount']
            if num_chunks == 0 and retry_count < 4:
                print("Index is empty. Waiting 60 seconds to check again...")
                time.sleep(60)
            elif num_chunks == 0 and retry_count == 4:
                print("Index is empty. Please investigate and re-index.")
            else:
                print(f"The index contains {num_chunks} chunks.")
                average_chunk_size = response['storageSize'] / num_chunks
                print(f"The average chunk size of the index is {average_chunk_size} bytes.")
                break
        else:
            if response.status_code == 404:
                print("The index does not exist. Please make sure the index was created correctly.")
            elif response.status_code == 403:
                print("Authentication Failure: Make sure you are using the correct key")
            else:
                print(f"Request failed. Status code: {response.status_code}")
            break


def generate_document_mapping(config: Dict) -> List[Dict]:
    """Generate document mapping from directory structure and optional CSV files.
    
    This function attempts to match documents across languages based on
    the document ID pattern in filenames (e.g., 1000-0, 1000-1, etc.)
    
    If csv_file is specified in the language config, URLs will be read from the CSV
    instead of being constructed from file paths.
    """
    
    languages = config.get("languages", ["en", "fr"])
    data_paths = config.get("data_paths_multilingual", {})
    
    # Build URL index from CSV files (if provided)
    url_from_csv = {}
    for lang in languages:
        lang_config = data_paths.get(lang, {})
        csv_file = lang_config.get("csv_file")
        
        if csv_file and os.path.exists(csv_file):
            url_from_csv[lang] = {}
            with open(csv_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    # Get the URL column (first column or 'URL'/'Url')
                    url = row.get('URL') or row.get('Url') or row.get('url') or list(row.values())[0]
                    # Get the filename column
                    filename = row.get('En_Filename') or row.get('Fr_Filename') or row.get('Filename') or list(row.values())[1]
                    
                    # Extract doc_id from filename (e.g., "1000-0" from "1000-0-some-title.html")
                    match = re.match(r'^(\d+-\d+)', filename)
                    if match:
                        doc_id = match.group(1)
                        url_from_csv[lang][doc_id] = url
            print(f"Loaded {len(url_from_csv[lang])} URLs from CSV for language '{lang}'")

    # Build file index for each language
    file_index = {}
    for lang in languages:
        lang_config = data_paths.get(lang, {})
        base_path = lang_config.get("base_path")
        url_prefix = lang_config.get("url_prefix", "")
        
        if not base_path or not os.path.exists(base_path):
            print(f"Warning: Base path for {lang} not found: {base_path}")
            continue
            
        file_index[lang] = {}
        for file_path in get_files_recursively(base_path):
            # Extract document ID from filename
            filename = os.path.basename(file_path)
            # Pattern: Extract leading number pattern like "1000-0", "1000-1", etc.
            match = re.match(r'^(\d+-\d+)', filename)
            if match:
                doc_id = match.group(1)
                
                # Use URL from CSV if available, otherwise construct from path
                if lang in url_from_csv and doc_id in url_from_csv[lang]:
                    url = url_from_csv[lang][doc_id]
                else:
                    url = url_prefix + os.path.relpath(file_path, base_path).replace("\\", "/")
                
                file_index[lang][doc_id] = {
                    "file_path": file_path,
                    "url": url
                }
    
    # Create mappings for documents that exist in at least one language
    all_doc_ids = set()
    for lang_files in file_index.values():
        all_doc_ids.update(lang_files.keys())
    
    mappings = []
    for doc_id in sorted(all_doc_ids):
        mapping = {"doc_id": doc_id}
        for lang in languages:
            if doc_id in file_index.get(lang, {}):
                mapping[lang] = file_index[lang][doc_id]
        mappings.append(mapping)
    
    return mappings


def create_multilingual_index(
    config: Dict,
    credential,
    form_recognizer_client=None,
    embedding_model_endpoint=None,
    embedding_model_key=None,
    use_layout=False,
    njobs=4,
    upload_batch_size=50
):
    """Create a multilingual index from the configuration."""
    
    service_name = config["search_service_name"]
    subscription_id = config["subscription_id"]
    resource_group = config["resource_group"]
    location = config["location"]
    index_name = config["index_name"]
    languages = config.get("languages", ["en", "fr"])
    primary_language = config.get("primary_language", languages[0])
    
    # Validate languages
    for lang in languages:
        if lang not in SUPPORTED_LANGUAGE_CODES:
            raise Exception(f"Language '{lang}' is not supported. Supported: {list(SUPPORTED_LANGUAGE_CODES.keys())}")
    
    # Check/create search service (only if credential is available)
    if credential:
        try:
            if check_if_search_service_exists(service_name, subscription_id, resource_group, credential):
                print(f"Using existing search service {service_name}")
            else:
                print(f"Creating search service {service_name}")
                create_search_service(service_name, subscription_id, resource_group, location, credential=credential)
        except Exception as e:
            print(f"Unable to verify if search service exists. Error: {e}")
            print("Proceeding to attempt to create index.")
    else:
        print("Skipping search service check (no Azure credential). Assuming service exists.")

    # Create the multilingual index
    admin_key = os.environ.get("AZURE_SEARCH_ADMIN_KEY", None)
    if not create_or_update_multilingual_search_index(
        service_name, 
        subscription_id, 
        resource_group, 
        index_name, 
        config["semantic_config_name"], 
        credential, 
        languages,
        vector_config_name=config.get("vector_config_name"),
        admin_key=admin_key
    ):
        raise Exception(f"Failed to create or update index {index_name}")

    # Load or generate document mapping
    mapping_file = config.get("document_mapping_file")
    if mapping_file and os.path.exists(mapping_file):
        print(f"Loading document mapping from {mapping_file}")
        with open(mapping_file, "r", encoding="utf-8") as f:
            document_mappings = json.load(f)
    else:
        print("Generating document mapping from directory structure...")
        document_mappings = generate_document_mapping(config)
        
        # Optionally save the generated mapping
        if mapping_file:
            os.makedirs(os.path.dirname(mapping_file), exist_ok=True)
            with open(mapping_file, "w", encoding="utf-8") as f:
                json.dump(document_mappings, f, indent=2, ensure_ascii=False)
            print(f"Saved generated document mapping to {mapping_file}")

    print(f"Processing {len(document_mappings)} document sets...")
    
    # Initialize search client for incremental uploads
    endpoint = f"https://{service_name}.search.windows.net/"
    if not admin_key:
        admin_key = json.loads(
            subprocess.run(
                f"az search admin-key show --subscription {subscription_id} --resource-group {resource_group} --service-name {service_name}",
                shell=True,
                capture_output=True,
            ).stdout
        )["primaryKey"]

    search_client = SearchClient(
        endpoint=endpoint,
        index_name=index_name,
        credential=AzureKeyCredential(admin_key),
    )
    
    # Process and upload documents incrementally
    add_embeddings = config.get("vector_config_name") and embedding_model_endpoint
    pending_docs = []  # Buffer for batch uploads
    total_indexed = 0
    global_doc_idx = 0  # Global index counter for unique IDs
    
    for doc_mapping in tqdm(document_mappings, desc="Processing and indexing documents"):
        try:
            multilingual_docs = process_multilingual_document(
                doc_mapping=doc_mapping,
                languages=languages,
                primary_language=primary_language,
                num_tokens=config.get("chunk_size", 1024),
                token_overlap=config.get("token_overlap", 0),
                add_embeddings=add_embeddings,
                embedding_endpoint=embedding_model_endpoint,
                embedding_key=embedding_model_key,
                azure_credential=credential,
                form_recognizer_client=form_recognizer_client,
                use_layout=use_layout
            )
            
            # Convert documents to upload format and add to pending batch
            for d in multilingual_docs:
                doc_dict = dataclasses.asdict(d)
                doc_dict.update({"@search.action": "upload", "id": str(global_doc_idx)})
                global_doc_idx += 1
                
                # Remove None values and empty contentVector
                if "contentVector" in doc_dict and doc_dict["contentVector"] is None:
                    del doc_dict["contentVector"]
                    
                # Clean up None values for language fields
                doc_dict = {k: v for k, v in doc_dict.items() if v is not None}
                
                pending_docs.append(doc_dict)
            
            # Upload when batch size is reached
            if len(pending_docs) >= upload_batch_size:
                _upload_batch(search_client, pending_docs[:upload_batch_size])
                total_indexed += len(pending_docs[:upload_batch_size])
                pending_docs = pending_docs[upload_batch_size:]
                
        except Exception as e:
            print(f"Error processing doc_id={doc_mapping.get('doc_id')}: {e}")

    # Upload any remaining documents
    if pending_docs:
        _upload_batch(search_client, pending_docs)
        total_indexed += len(pending_docs)

    if total_indexed == 0:
        raise Exception("No documents were processed and indexed successfully.")

    print(f"Total chunks indexed: {total_indexed}")

    # Validate
    print("Validating index...")
    validate_index(service_name, subscription_id, resource_group, index_name)
    print("Index validation completed")


def _upload_batch(search_client: SearchClient, batch: List[Dict], max_retries: int = 3):
    """Upload a batch of documents to the search index.
    
    Handles RequestEntityTooLargeError by automatically splitting the batch in half
    and retrying recursively.
    """
    if not batch:
        return
    
    try:
        results = search_client.upload_documents(documents=batch)
        num_failures = 0
        errors = set()
        for result in results:
            if not result.succeeded:
                print(f"Indexing Failed for {result.key} with ERROR: {result.error_message}")
                num_failures += 1
                errors.add(result.error_message)
        if num_failures > 0:
            raise Exception(
                f"INDEXING FAILED for {num_failures} documents. Please recreate the index. "
                f"Error Messages: {list(errors)}"
            )
    except Exception as e:
        error_str = str(e).lower()
        if "request entity too large" in error_str or "413" in error_str or "requestentitytoolarge" in error_str:
            if len(batch) == 1:
                # Single document is too large, skip it
                print(f"ERROR: Single document too large to upload (id={batch[0].get('id')}). Skipping.")
                return
            # Split batch in half and retry
            mid = len(batch) // 2
            print(f"Batch too large ({len(batch)} docs), splitting into two batches of {mid} and {len(batch) - mid}...")
            _upload_batch(search_client, batch[:mid], max_retries)
            _upload_batch(search_client, batch[mid:], max_retries)
        else:
            raise


def valid_range(n):
    n = int(n)
    if n < 1 or n > 32:
        raise argparse.ArgumentTypeError("njobs must be an Integer between 1 and 32.")
    return n


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Multilingual Data Preparation for Azure Cognitive Search")
    parser.add_argument("--config", type=str, required=True, 
                        help="Path to config file containing settings for multilingual data preparation")
    parser.add_argument("--form-rec-resource", type=str, 
                        help="Name of your Form Recognizer resource for PDF cracking")
    parser.add_argument("--form-rec-key", type=str, 
                        help="Key for your Form Recognizer resource")
    parser.add_argument("--form-rec-use-layout", default=True, action='store_true', 
                        help="Whether to use Layout model for PDF cracking")
    parser.add_argument("--njobs", type=valid_range, default=4, 
                        help="Number of parallel jobs (1-32). Default=4")
    parser.add_argument("--embedding-model-endpoint", type=str, 
                        help="Endpoint for the embedding model for vector search")
    parser.add_argument("--embedding-model-key", type=str, 
                        help="Key for the embedding model")
    parser.add_argument("--search-admin-key", type=str, 
                        help="Admin key for the search service")
    parser.add_argument("--upload-batch-size", type=int, default=10,
                        help="Number of documents to upload per batch. Default=10. Use smaller values when embeddings are enabled.")
    parser.add_argument("--generate-mapping-only", action='store_true',
                        help="Only generate document mapping file without indexing")
    
    args = parser.parse_args()

    with open(args.config) as f:
        config_list = json.load(f)

    # Only use AzureCliCredential if we need it (no keys provided)
    credential = None
    if not args.search_admin_key or not args.embedding_model_key:
        try:
            credential = AzureCliCredential()
            # Test if it works
            credential.get_token("https://management.azure.com/.default")
        except Exception as e:
            print(f"Warning: Azure CLI credential not available: {e}")
            if not args.search_admin_key:
                raise Exception("Azure CLI not available and --search-admin-key not provided. Please provide the search admin key.")
            credential = None
    
    form_recognizer_client = None

    print("Multilingual Data Preparation Script Started")
    
    if args.search_admin_key:
        os.environ["AZURE_SEARCH_ADMIN_KEY"] = args.search_admin_key

    if args.form_rec_resource and args.form_rec_key:
        os.environ["FORM_RECOGNIZER_ENDPOINT"] = f"https://{args.form_rec_resource}.cognitiveservices.azure.com/"
        os.environ["FORM_RECOGNIZER_KEY"] = args.form_rec_key
        form_recognizer_client = DocumentIntelligenceClient(
            endpoint=f"https://{args.form_rec_resource}.cognitiveservices.azure.com/", 
            credential=AzureKeyCredential(args.form_rec_key)
        )
        print(f"Using Form Recognizer resource {args.form_rec_resource}")

    for index_config in config_list:
        print(f"\nPreparing multilingual data for index: {index_config['index_name']}")
        
        if args.generate_mapping_only:
            # Only generate mapping file
            mappings = generate_document_mapping(index_config)
            mapping_file = index_config.get("document_mapping_file", "document_mapping.json")
            os.makedirs(os.path.dirname(mapping_file) if os.path.dirname(mapping_file) else ".", exist_ok=True)
            with open(mapping_file, "w", encoding="utf-8") as f:
                json.dump(mappings, f, indent=2, ensure_ascii=False)
            print(f"Generated document mapping with {len(mappings)} entries: {mapping_file}")
            continue
        
        if index_config.get("vector_config_name") and not args.embedding_model_endpoint:
            raise Exception(
                "Vector search is enabled but no embedding model endpoint provided. "
                "Please provide --embedding-model-endpoint or disable vector search."
            )
    
        create_multilingual_index(
            index_config, 
            credential, 
            form_recognizer_client, 
            embedding_model_endpoint=args.embedding_model_endpoint,
            embedding_model_key=args.embedding_model_key,
            use_layout=args.form_rec_use_layout, 
            njobs=args.njobs,
            upload_batch_size=args.upload_batch_size
        )
        print(f"Multilingual data preparation for index {index_config['index_name']} completed")

    print(f"\nMultilingual Data Preparation Script Completed. {len(config_list)} indexes processed.")

"""Script to fix URL fields in the Azure Cognitive Search index.

This script reads the correct URLs from the document_mapping.json file and updates 
the url_en and url_fr fields in the search index documents.

The old index was created with incorrect URLs (missing 1000-series/serie-1000 in path).
This script fixes them using the correct URLs from document_mapping.json.

Usage:
    python fix_index_urls.py --config config_multilingual.json --search-admin-key <key>
    
    Or using environment variable:
    set AZURE_SEARCH_ADMIN_KEY=<key>
    python fix_index_urls.py --config config_multilingual.json
    
    Dry run first:
    python fix_index_urls.py --config config_multilingual.json --dry-run
"""

import argparse
import json
import os
import re
import sys
from typing import Dict, List, Optional, Tuple

from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from dotenv import load_dotenv
from tqdm import tqdm

load_dotenv()


def load_url_mapping_from_document_mapping(mapping_file: str) -> Tuple[Dict[str, str], Dict[str, str]]:
    """Load URL mappings from document_mapping.json file.
    
    Returns two dicts: (url_mapping_en, url_mapping_fr)
    Each maps doc_id (e.g., "1000-0") to the correct URL.
    """
    url_mapping_en = {}
    url_mapping_fr = {}
    
    if not os.path.exists(mapping_file):
        print(f"Error: Document mapping file not found: {mapping_file}")
        return url_mapping_en, url_mapping_fr
    
    with open(mapping_file, 'r', encoding='utf-8') as f:
        mappings = json.load(f)
    
    for mapping in mappings:
        doc_id = mapping.get("doc_id")
        if not doc_id:
            continue
        
        # Get English URL
        en_data = mapping.get("en", {})
        if en_data and "url" in en_data:
            url_mapping_en[doc_id] = en_data["url"]
        
        # Get French URL
        fr_data = mapping.get("fr", {})
        if fr_data and "url" in fr_data:
            url_mapping_fr[doc_id] = fr_data["url"]
    
    print(f"Loaded {len(url_mapping_en)} English URLs and {len(url_mapping_fr)} French URLs from {mapping_file}")
    return url_mapping_en, url_mapping_fr


def get_all_documents(search_client: SearchClient) -> List[Dict]:
    """Retrieve all documents from the search index."""
    documents = []
    results = search_client.search(
        search_text="*",
        select=["id", "doc_id", "url_en", "url_fr"],
        include_total_count=True
    )
    
    for doc in results:
        documents.append(dict(doc))
    
    print(f"Retrieved {len(documents)} documents from the index")
    return documents


def extract_base_doc_id(doc: Dict) -> Optional[str]:
    """Extract the base doc_id from document fields.
    
    The doc_id in the index might be like "1000-0_chunk_0", we need "1000-0".
    """
    doc_id = doc.get("doc_id", "")
    
    # Try to extract the base doc_id (before _chunk_)
    if "_chunk_" in doc_id:
        base_doc_id = doc_id.split("_chunk_")[0]
        return base_doc_id
    
    # Try to extract from doc_id directly
    match = re.match(r'^(\d+-\d+)', doc_id)
    if match:
        return match.group(1)
    
    return doc_id if doc_id else None


def fix_urls(
    search_client: SearchClient,
    url_mapping_en: Dict[str, str],
    url_mapping_fr: Dict[str, str],
    dry_run: bool = False,
    batch_size: int = 100
) -> Dict[str, int]:
    """Fix URLs in the search index.
    
    Returns statistics about the operation.
    """
    stats = {
        "total_documents": 0,
        "documents_updated": 0,
        "documents_skipped": 0,
        "url_en_fixed": 0,
        "url_fr_fixed": 0,
        "no_mapping_found": 0,
        "errors": 0
    }
    
    # Get all documents
    documents = get_all_documents(search_client)
    stats["total_documents"] = len(documents)
    
    # Prepare updates
    updates = []
    sample_changes = []
    
    for doc in tqdm(documents, desc="Analyzing documents"):
        base_doc_id = extract_base_doc_id(doc)
        
        if not base_doc_id:
            stats["documents_skipped"] += 1
            continue
        
        update_needed = False
        update_doc = {
            "@search.action": "merge",
            "id": doc["id"]
        }
        
        change_info = {
            "id": doc["id"],
            "doc_id": doc.get("doc_id"),
            "base_doc_id": base_doc_id
        }
        
        # Check and fix url_en
        current_url_en = doc.get("url_en", "")
        correct_url_en = url_mapping_en.get(base_doc_id)
        
        if correct_url_en:
            if current_url_en != correct_url_en:
                update_doc["url_en"] = correct_url_en
                update_needed = True
                stats["url_en_fixed"] += 1
                change_info["url_en_old"] = current_url_en
                change_info["url_en_new"] = correct_url_en
        
        # Check and fix url_fr
        current_url_fr = doc.get("url_fr", "")
        correct_url_fr = url_mapping_fr.get(base_doc_id)
        
        if correct_url_fr:
            if current_url_fr != correct_url_fr:
                update_doc["url_fr"] = correct_url_fr
                update_needed = True
                stats["url_fr_fixed"] += 1
                change_info["url_fr_old"] = current_url_fr
                change_info["url_fr_new"] = correct_url_fr
        
        if not correct_url_en and not correct_url_fr:
            stats["no_mapping_found"] += 1
        
        if update_needed:
            updates.append(update_doc)
            stats["documents_updated"] += 1
            if len(sample_changes) < 5:
                sample_changes.append(change_info)
        else:
            stats["documents_skipped"] += 1
    
    # Show sample of changes
    if sample_changes:
        print("\n" + "=" * 80)
        print("SAMPLE URL CHANGES (first 5)")
        print("=" * 80)
        for change in sample_changes:
            print(f"\nDocument: {change['doc_id']} (base: {change['base_doc_id']})")
            if "url_en_old" in change:
                print(f"  url_en (OLD): {change['url_en_old']}...")
                print(f"  url_en (NEW): {change['url_en_new']}...")
            if "url_fr_old" in change:
                print(f"  url_fr (OLD): {change['url_fr_old']}...")
                print(f"  url_fr (NEW): {change['url_fr_new']}...")
        if len(updates) > 5:
            print(f"\n... and {len(updates) - 5} more documents to update")
    
    # Apply updates
    if dry_run:
        print(f"\n[DRY RUN] Would update {len(updates)} documents")
    else:
        if updates:
            print(f"\nUpdating {len(updates)} documents...")
            
            # Upload in batches
            for i in tqdm(range(0, len(updates), batch_size), desc="Uploading fixes"):
                batch = updates[i:i + batch_size]
                try:
                    results = search_client.merge_or_upload_documents(documents=batch)
                    for result in results:
                        if not result.succeeded:
                            print(f"Error updating document {result.key}: {result.error_message}")
                            stats["errors"] += 1
                except Exception as e:
                    print(f"Error uploading batch: {e}")
                    stats["errors"] += len(batch)
        else:
            print("\nNo documents need to be updated.")
    
    return stats


def main():
    parser = argparse.ArgumentParser(description="Fix URL fields in Azure Search index")
    parser.add_argument("--config", type=str, required=True,
                        help="Path to config file (e.g., config_multilingual.json)")
    parser.add_argument("--mapping-file", type=str, default="document_mapping.json",
                        help="Path to document_mapping.json with correct URLs (default: document_mapping.json)")
    parser.add_argument("--search-admin-key", type=str,
                        help="Admin key for the search service")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be changed without making changes")
    parser.add_argument("--batch-size", type=int, default=100,
                        help="Number of documents to update per batch (default: 100)")
    
    args = parser.parse_args()
    
    # Load config
    with open(args.config, 'r', encoding='utf-8') as f:
        config_list = json.load(f)
    
    if not config_list:
        print("Error: No configuration found in config file")
        sys.exit(1)
    
    config = config_list[0]  # Use first config
    
    # Get search service details
    service_name = config.get("search_service_name")
    index_name = config.get("index_name")
    
    if not service_name or not index_name:
        print("Error: search_service_name and index_name are required in config")
        sys.exit(1)
    
    # Get admin key
    admin_key = args.search_admin_key or os.environ.get("AZURE_SEARCH_ADMIN_KEY") or os.environ.get("AZURE_SEARCH_KEY")
    
    if not admin_key:
        print("Error: Search admin key is required. Provide via --search-admin-key or AZURE_SEARCH_ADMIN_KEY env var")
        sys.exit(1)
    
    # Load URL mappings from document_mapping.json
    print(f"Loading correct URLs from {args.mapping_file}...")
    url_mapping_en, url_mapping_fr = load_url_mapping_from_document_mapping(args.mapping_file)
    
    if not url_mapping_en and not url_mapping_fr:
        print("Error: No URL mappings loaded from document mapping file")
        sys.exit(1)
    
    # Connect to search service
    endpoint = f"https://{service_name}.search.windows.net"
    credential = AzureKeyCredential(admin_key)
    
    print(f"\nConnecting to search service: {service_name}")
    print(f"Index: {index_name}")
    
    search_client = SearchClient(
        endpoint=endpoint,
        index_name=index_name,
        credential=credential
    )
    
    # Fix URLs
    print(f"\n{'=' * 80}")
    if args.dry_run:
        print("MODE: DRY RUN - No changes will be made")
    else:
        print("MODE: LIVE - Changes will be applied to the index")
    print(f"{'=' * 80}\n")
    
    stats = fix_urls(
        search_client=search_client,
        url_mapping_en=url_mapping_en,
        url_mapping_fr=url_mapping_fr,
        dry_run=args.dry_run,
        batch_size=args.batch_size
    )
    
    # Print summary
    print(f"\n{'=' * 80}")
    print("SUMMARY")
    print(f"{'=' * 80}")
    print(f"Total documents in index:     {stats['total_documents']}")
    print(f"Documents to update:          {stats['documents_updated']}")
    print(f"Documents skipped (no change): {stats['documents_skipped']}")
    print(f"No mapping found:             {stats['no_mapping_found']}")
    print(f"URL (English) fixes:          {stats['url_en_fixed']}")
    print(f"URL (French) fixes:           {stats['url_fr_fixed']}")
    if stats['errors'] > 0:
        print(f"Errors:                       {stats['errors']}")
    
    if args.dry_run and stats['documents_updated'] > 0:
        print(f"\n>>> To apply these changes, run again without --dry-run flag <<<")


if __name__ == "__main__":
    main()

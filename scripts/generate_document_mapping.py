"""Generate Document Mapping for Multilingual Index.

This script scans the English and French document directories and attempts to 
match documents based on their document ID pattern (e.g., 1000-0, 1000-1, etc.).

The script uses the following matching strategy:
1. Extract document ID from filename (e.g., "1000-0" from "1000-0-foundation-framework.html")
2. Match documents with the same ID across languages
3. Generate a mapping file that links EN and FR versions

Usage:
    python generate_document_mapping.py \
        --en-path data_en/html \
        --fr-path data/html \
        --en-url-prefix "https://www.canada.ca/en/..." \
        --fr-url-prefix "https://www.canada.ca/fr/..." \
        --output document_mapping.json
"""

import argparse
import json
import os
import re
from collections import defaultdict
from typing import Dict, List, Optional, Tuple


def extract_doc_id(filename: str) -> Optional[str]:
    """Extract document ID from filename.
    
    Patterns supported:
    - "1000-0-some-title.html" -> "1000-0"
    - "1000-10-some-title.html" -> "1000-10"
    - "5019-4-some-title.html" -> "5019-4"
    
    Args:
        filename: The filename to extract ID from
        
    Returns:
        The document ID or None if no pattern matches
    """
    # Match patterns like "1000-0", "1000-10", "5019-4", etc.
    match = re.match(r'^(\d+-\d+)', filename)
    if match:
        return match.group(1)
    return None


def get_files_recursively(directory_path: str) -> List[str]:
    """Get all files in a directory recursively."""
    file_paths = []
    for dirpath, _, files in os.walk(directory_path):
        for file_name in files:
            file_path = os.path.join(dirpath, file_name)
            file_paths.append(file_path)
    return file_paths


def build_file_index(base_path: str, url_prefix: str = "") -> Dict[str, Dict]:
    """Build an index of files by document ID.
    
    Args:
        base_path: Base directory path
        url_prefix: URL prefix to prepend to relative paths
        
    Returns:
        Dictionary mapping doc_id to file info
    """
    index = {}
    
    if not os.path.exists(base_path):
        print(f"Warning: Path does not exist: {base_path}")
        return index
    
    for file_path in get_files_recursively(base_path):
        filename = os.path.basename(file_path)
        doc_id = extract_doc_id(filename)
        
        if doc_id:
            rel_path = os.path.relpath(file_path, base_path).replace("\\", "/")
            index[doc_id] = {
                "file_path": file_path.replace("\\", "/"),
                "url": url_prefix + rel_path if url_prefix else rel_path,
                "filename": filename
            }
    
    return index


def generate_mapping(
    en_path: str,
    fr_path: str,
    en_url_prefix: str = "",
    fr_url_prefix: str = "",
    require_both_languages: bool = False
) -> List[Dict]:
    """Generate document mapping by matching EN and FR documents.
    
    Args:
        en_path: Path to English documents
        fr_path: Path to French documents
        en_url_prefix: URL prefix for English documents
        fr_url_prefix: URL prefix for French documents
        require_both_languages: If True, only include docs that exist in both languages
        
    Returns:
        List of document mappings
    """
    print(f"Scanning English documents from: {en_path}")
    en_index = build_file_index(en_path, en_url_prefix)
    print(f"Found {len(en_index)} English documents")
    
    print(f"Scanning French documents from: {fr_path}")
    fr_index = build_file_index(fr_path, fr_url_prefix)
    print(f"Found {len(fr_index)} French documents")
    
    # Get all unique document IDs
    all_doc_ids = set(en_index.keys()) | set(fr_index.keys())
    print(f"Total unique document IDs: {len(all_doc_ids)}")
    
    # Count matches
    both_languages = set(en_index.keys()) & set(fr_index.keys())
    en_only = set(en_index.keys()) - set(fr_index.keys())
    fr_only = set(fr_index.keys()) - set(en_index.keys())
    
    print(f"\nMatching Statistics:")
    print(f"  Documents in both EN and FR: {len(both_languages)}")
    print(f"  Documents only in EN: {len(en_only)}")
    print(f"  Documents only in FR: {len(fr_only)}")
    
    # Generate mappings
    mappings = []
    
    for doc_id in sorted(all_doc_ids):
        has_en = doc_id in en_index
        has_fr = doc_id in fr_index
        
        if require_both_languages and not (has_en and has_fr):
            continue
        
        mapping = {"doc_id": doc_id}
        
        if has_en:
            mapping["en"] = {
                "file_path": en_index[doc_id]["file_path"],
                "url": en_index[doc_id]["url"]
            }
        
        if has_fr:
            mapping["fr"] = {
                "file_path": fr_index[doc_id]["file_path"],
                "url": fr_index[doc_id]["url"]
            }
        
        mappings.append(mapping)
    
    return mappings


def print_unmatched_documents(en_path: str, fr_path: str):
    """Print documents that don't have a matching translation."""
    en_index = build_file_index(en_path)
    fr_index = build_file_index(fr_path)
    
    en_only = set(en_index.keys()) - set(fr_index.keys())
    fr_only = set(fr_index.keys()) - set(en_index.keys())
    
    if en_only:
        print("\n=== Documents only in English ===")
        for doc_id in sorted(en_only):
            print(f"  {doc_id}: {en_index[doc_id]['filename']}")
    
    if fr_only:
        print("\n=== Documents only in French ===")
        for doc_id in sorted(fr_only):
            print(f"  {doc_id}: {fr_index[doc_id]['filename']}")


def main():
    parser = argparse.ArgumentParser(
        description="Generate document mapping for multilingual index"
    )
    parser.add_argument(
        "--en-path", 
        type=str, 
        default="data_en/html",
        help="Path to English documents directory"
    )
    parser.add_argument(
        "--fr-path", 
        type=str, 
        default="data/html",
        help="Path to French documents directory"
    )
    parser.add_argument(
        "--en-url-prefix", 
        type=str, 
        default="https://www.canada.ca/en/department-national-defence/corporate/policies-standards/defence-administrative-orders-directives/",
        help="URL prefix for English documents"
    )
    parser.add_argument(
        "--fr-url-prefix", 
        type=str, 
        default="https://www.canada.ca/fr/ministere-defense-nationale/organisation/politiques-normes/directives-ordonnances-administratives-defense/",
        help="URL prefix for French documents"
    )
    parser.add_argument(
        "--output", 
        type=str, 
        default="document_mapping.json",
        help="Output file path for the generated mapping"
    )
    parser.add_argument(
        "--require-both", 
        action="store_true",
        help="Only include documents that exist in both languages"
    )
    parser.add_argument(
        "--show-unmatched", 
        action="store_true",
        help="Print list of documents that don't have a matching translation"
    )
    
    args = parser.parse_args()
    
    if args.show_unmatched:
        print_unmatched_documents(args.en_path, args.fr_path)
        return
    
    mappings = generate_mapping(
        en_path=args.en_path,
        fr_path=args.fr_path,
        en_url_prefix=args.en_url_prefix,
        fr_url_prefix=args.fr_url_prefix,
        require_both_languages=args.require_both
    )
    
    # Save to file
    output_dir = os.path.dirname(args.output)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
    
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(mappings, f, indent=2, ensure_ascii=False)
    
    print(f"\nGenerated mapping with {len(mappings)} document sets")
    print(f"Saved to: {args.output}")


if __name__ == "__main__":
    main()

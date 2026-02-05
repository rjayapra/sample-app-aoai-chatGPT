"""Script to fix filepath fields in the Azure Search index.

This script updates filepath_en and filepath_fr fields to contain only the filename
instead of the full relative path.
"""

import os
import json
import argparse
from dotenv import load_dotenv
from azure.search.documents import SearchClient
from azure.core.credentials import AzureKeyCredential

# Load environment from parent directory
import pathlib
env_path = pathlib.Path(__file__).parent.parent / ".env"
load_dotenv(env_path)


def fix_filepaths(dry_run: bool = True):
    """Fix filepath fields to contain only filenames."""
    
    service_name = os.getenv("AZURE_SEARCH_SERVICE")
    index_name = os.getenv("AZURE_SEARCH_INDEX")
    admin_key = os.getenv("AZURE_SEARCH_ADMIN_KEY") or os.getenv("AZURE_SEARCH_KEY")
    
    print(f"Service: {service_name}")
    print(f"Index: {index_name}")
    print(f"Dry run: {dry_run}")
    
    endpoint = f"https://{service_name}.search.windows.net"
    credential = AzureKeyCredential(admin_key)
    
    search_client = SearchClient(
        endpoint=endpoint,
        index_name=index_name,
        credential=credential
    )
    
    # Get all documents
    print("\nFetching documents...")
    results = search_client.search(
        search_text="*",
        select=["id", "filepath_en", "filepath_fr"],
        top=10000
    )
    
    documents_to_update = []
    en_fixed = 0
    fr_fixed = 0
    
    for doc in results:
        doc_id = doc.get("id")
        filepath_en = doc.get("filepath_en", "")
        filepath_fr = doc.get("filepath_fr", "")
        
        update_doc = {"id": doc_id}
        needs_update = False
        
        # Fix English filepath if it contains path separators
        if filepath_en and (os.sep in filepath_en or "/" in filepath_en or "\\" in filepath_en):
            new_filepath_en = os.path.basename(filepath_en.replace("\\", "/"))
            if new_filepath_en != filepath_en:
                update_doc["filepath_en"] = new_filepath_en
                needs_update = True
                en_fixed += 1
                if dry_run and en_fixed <= 3:
                    print(f"  EN: '{filepath_en}' -> '{new_filepath_en}'")
        
        # Fix French filepath if it contains path separators
        if filepath_fr and (os.sep in filepath_fr or "/" in filepath_fr or "\\" in filepath_fr):
            new_filepath_fr = os.path.basename(filepath_fr.replace("\\", "/"))
            if new_filepath_fr != filepath_fr:
                update_doc["filepath_fr"] = new_filepath_fr
                needs_update = True
                fr_fixed += 1
                if dry_run and fr_fixed <= 3:
                    print(f"  FR: '{filepath_fr}' -> '{new_filepath_fr}'")
        
        if needs_update:
            documents_to_update.append(update_doc)
    
    print(f"\nFound {len(documents_to_update)} documents needing filepath fixes")
    print(f"  - English filepaths to fix: {en_fixed}")
    print(f"  - French filepaths to fix: {fr_fixed}")
    
    if dry_run:
        print("\nDry run complete. Run with --apply to make changes.")
        return
    
    if not documents_to_update:
        print("No documents to update.")
        return
    
    # Upload in batches
    batch_size = 100
    total_updated = 0
    
    for i in range(0, len(documents_to_update), batch_size):
        batch = documents_to_update[i:i+batch_size]
        try:
            result = search_client.merge_documents(batch)
            succeeded = sum(1 for r in result if r.succeeded)
            total_updated += succeeded
            print(f"Batch {i//batch_size + 1}: Updated {succeeded}/{len(batch)} documents")
        except Exception as e:
            print(f"Error updating batch {i//batch_size + 1}: {e}")
    
    print(f"\nTotal documents updated: {total_updated}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fix filepath fields in Azure Search index")
    parser.add_argument("--apply", action="store_true", help="Apply the changes (default is dry run)")
    args = parser.parse_args()
    
    fix_filepaths(dry_run=not args.apply)

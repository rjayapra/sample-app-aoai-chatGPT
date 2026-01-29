# Multilingual Index Architecture for Oscar

This document describes the architecture for creating a unified multilingual Azure Cognitive Search index that combines English and French documents.

## Overview

Instead of maintaining separate indexes for English and French content, this architecture uses a **single unified index** with language-specific fields. This ensures that:

1. **Consistent Results**: When a user asks about "dress code" in English or "code vestimentaire" in French, they receive equivalent results from the respective language content.
2. **Document Alignment**: Related EN/FR documents are stored in the same index document, linked by a common `doc_id`.
3. **Efficient Vector Search**: A single vector embedding (from the primary language) enables semantic search across both languages.

## Index Schema

The multilingual index includes the following fields:

| Field | Type | Description |
|-------|------|-------------|
| `id` | Edm.String | Unique document ID (key) |
| `doc_id` | Edm.String | Document identifier linking translations (e.g., "1000-0") |
| `content_en` | Edm.String | English content (uses `en.lucene` analyzer) |
| `content_fr` | Edm.String | French content (uses `fr.lucene` analyzer) |
| `title_en` | Edm.String | English title |
| `title_fr` | Edm.String | French title |
| `url_en` | Edm.String | URL to English document |
| `url_fr` | Edm.String | URL to French document |
| `filepath_en` | Edm.String | File path to English document |
| `filepath_fr` | Edm.String | File path to French document |
| `contentVector` | Collection(Edm.Single) | Vector embedding (from primary language) |
| `metadata` | Edm.String | Additional metadata (JSON) |
| `image_mapping` | Edm.String | Image mappings (JSON) |

## Input Requirements

### 1. Document Mapping File

A JSON file that maps document IDs to their language-specific file paths and URLs.

**File**: `scripts/document_mapping.json`

**Structure**:
```json
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
    },
    {
        "doc_id": "1000-1",
        "en": {
            "file_path": "data_en/html/1000/1000-1-defence-orders.html",
            "url": "https://example.com/en/1000-1"
        },
        "fr": {
            "file_path": "data/html/1000/1000-1-ordonnances-defense.html",
            "url": "https://example.com/fr/1000-1"
        }
    }
]
```

**Notes**:
- `doc_id`: Unique identifier for the document pair (typically the document number)
- Documents don't need to exist in both languages - the script handles missing translations
- URLs should point to the source/reference document

### 2. Document Directories

Organize your documents in language-specific directories:

```
data_en/
└── html/
    ├── 1000/
    │   ├── 1000-0-foundation-framework.html
    │   ├── 1000-1-defence-orders.html
    │   └── ...
    ├── 1001/
    └── ...

data/  (French documents)
└── html/
    ├── 1000/
    │   ├── 1000-0-cadre-principal.html
    │   ├── 1000-1-ordonnances-defense.html
    │   └── ...
    └── ...
```

### 3. Configuration File

**File**: `scripts/config_multilingual.json`

```json
[
    {
        "location": "eastus",
        "subscription_id": "your-subscription-id",
        "resource_group": "your-resource-group",
        "search_service_name": "your-search-service",
        "index_name": "oscar-multilingual-index",
        "chunk_size": 1024,
        "token_overlap": 128,
        "semantic_config_name": "multilingual-semantic-config",
        "vector_config_name": "multilingual-vector-config",
        "languages": ["en", "fr"],
        "primary_language": "en",
        "document_mapping_file": "scripts/document_mapping.json",
        "data_paths_multilingual": {
            "en": {
                "base_path": "data_en/html",
                "url_prefix": "https://www.canada.ca/en/..."
            },
            "fr": {
                "base_path": "data/html",
                "url_prefix": "https://www.canada.ca/fr/..."
            }
        }
    }
]
```

## Usage Instructions

### Step 1: Generate Document Mapping

If you don't have a document mapping file, generate one automatically:

```powershell
cd scripts

# Generate mapping from directory structure
python generate_document_mapping.py \
    --en-path "../data_en/html" \
    --fr-path "../data/html" \
    --en-url-prefix "https://www.canada.ca/en/department-national-defence/..." \
    --fr-url-prefix "https://www.canada.ca/fr/ministere-defense-nationale/..." \
    --output document_mapping.json

# View unmatched documents (optional)
python generate_document_mapping.py --show-unmatched
```

The script matches documents by extracting the document ID pattern (e.g., "1000-0") from filenames.

### Step 2: Review and Edit Mapping

Review `document_mapping.json` and:
- Fix any incorrect matches
- Add manual mappings for documents with non-standard naming
- Remove documents you don't want indexed

### Step 3: Create the Multilingual Index

```powershell
cd scripts

# Without vector search
python data_preparation_multilingual.py \
    --config config_multilingual.json \
    --search-admin-key "your-search-admin-key"

# With vector search
python data_preparation_multilingual.py \
    --config config_multilingual.json \
    --embedding-model-endpoint "https://your-aoai.openai.azure.com/openai/deployments/text-embedding-ada-002/embeddings?api-version=2024-03-01-Preview" \
    --search-admin-key "your-search-admin-key"

# With PDF support
python data_preparation_multilingual.py \
    --config config_multilingual.json \
    --form-rec-resource "your-form-recognizer" \
    --form-rec-key "your-form-recognizer-key" \
    --embedding-model-endpoint "..." \
    --search-admin-key "..."
```

### Step 4: Verify the Index

After indexing, verify in Azure Portal:
1. Go to your Azure Cognitive Search service
2. Navigate to Indexes > `oscar-multilingual-index`
3. Use Search Explorer to test queries in both languages

## Query Strategies

### Language-Specific Search

When querying the index, use the appropriate content field based on user's language:

**English Query**:
```json
{
    "search": "dress code",
    "searchFields": "content_en,title_en",
    "select": "doc_id,content_en,title_en,url_en"
}
```

**French Query**:
```json
{
    "search": "code vestimentaire",
    "searchFields": "content_fr,title_fr",
    "select": "doc_id,content_fr,title_fr,url_fr"
}
```

### Cross-Language Search (Vector)

Use vector search to find semantically similar content regardless of query language:

```json
{
    "vectorQueries": [{
        "vector": [/* embedding of query */],
        "fields": "contentVector",
        "k": 5
    }],
    "select": "doc_id,content_en,content_fr,url_en,url_fr"
}
```

## Application Integration

Update your application to:

1. **Detect User Language**: Determine if the user is querying in English or French
2. **Select Appropriate Fields**: Query `content_en` for English users, `content_fr` for French users
3. **Return Correct URLs**: Return `url_en` or `url_fr` based on user language
4. **Handle Missing Translations**: If a document only exists in one language, gracefully handle the missing field

### Example Python Code

```python
def search_documents(query: str, language: str = "en"):
    search_fields = f"content_{language},title_{language}"
    select_fields = f"doc_id,content_{language},title_{language},url_{language}"
    
    results = search_client.search(
        search_text=query,
        search_fields=search_fields.split(","),
        select=select_fields.split(","),
        query_type="semantic",
        semantic_configuration_name="multilingual-semantic-config"
    )
    
    return list(results)
```

## Troubleshooting

### Unmatched Documents

Use the mapping generator to identify documents without translations:

```powershell
python generate_document_mapping.py --show-unmatched
```

### Chunk Alignment Issues

The script chunks EN and FR documents independently. If chunk counts differ:
- Shorter documents may have fewer chunks
- Missing chunks are handled by leaving the corresponding language field empty

### Vector Embedding Language

The `primary_language` setting determines which content is used for vector embeddings:
- Set to `"en"` to embed English content (recommended for English-primary users)
- Set to `"fr"` to embed French content
- Consider using a multilingual embedding model for best cross-language results

## Files Created

| File | Description |
|------|-------------|
| `data_preparation_multilingual.py` | Main script for multilingual indexing |
| `generate_document_mapping.py` | Utility to generate document mappings |
| `config_multilingual.json` | Configuration template |
| `document_mapping_sample.json` | Sample document mapping |
| `README_MULTILINGUAL.md` | This documentation |

## Environment Variables

| Variable | Description |
|----------|-------------|
| `AZURE_SEARCH_ADMIN_KEY` | Search service admin key |
| `VECTOR_DIMENSION` | Vector dimension (default: 1536) |
| `FORM_RECOGNIZER_ENDPOINT` | Form Recognizer endpoint (for PDFs) |
| `FORM_RECOGNIZER_KEY` | Form Recognizer key |

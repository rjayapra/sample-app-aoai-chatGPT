# Step 1: Generate document mapping (already done - found 325 matching pairs)
python generate_document_mapping.py --en-path "../data_en/html" --fr-path "../data/html" --output document_mapping.json

# Step 2: Create the multilingual index
python data_preparation_multilingual.py --config config_multilingual.json \
    --embedding-model-endpoint "https://nd-dn-oscar2-dev-aoi.openai.azure.com/openai/deployments/embedding/embeddings?api-version=2023-05-15" \
    --embedding-model-key "d05d6891654544aeaa04a74a46e85f68"     
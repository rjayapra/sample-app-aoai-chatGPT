# Step 1: Generate document mapping (already done - found 325 matching pairs)
python generate_document_mapping.py --en-path "../data_en/html" --fr-path "../data/html" --output document_mapping.json

# Step 2: Create the multilingual index
python data_preparation_multilingual.py --config config_multilingual.json \
    --embedding-model-endpoint "https://cog-3xejuk4xpcx5c.openai.azure.com/openai/deployments/embedding-large/embeddings?api-version=2023-05-15" \
    --embedding-model-key "39cc91ddf83b4ea4a780c4b3c90feb0b"     
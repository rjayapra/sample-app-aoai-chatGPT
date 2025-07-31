# !/bin/bash

datevar=$(date +%d_%m_%Y)
echo "Building Docker image for date: $datevar"
az acr build --platform linux/amd64 --registry demoksregistry --image sample-app-aoai-chatgpt:$datevar --file WebApp.Dockerfile .
#docker buildx build --platform linux/amd64 --output "type=docker,oci-mediatypes=false" --file WebApp.Dockerfile --tag demoksregistry.azurecr.io/sample-app-aoai-chatgpt:$datevar .
#docker build --platform linux/amd64 --file WebApp.Dockerfile --tag demoksregistry.azurecr.io/sample-app-aoai-chatgpt:$datevar .
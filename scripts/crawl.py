import csv
import requests
import os
from azure.storage.blob import BlobServiceClient
from urllib.parse import urljoin
import logging
from typing import List, Tuple
from azure.identity import DefaultAzureCredential

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class WebPageCrawler:
    def __init__(self, storage_account_name: str, container_name: str):
        """
        Initialize the web page crawler with Azure Storage using default credentials.
        
        Args:
            storage_account_name: Azure Storage account name
            container_name: Name of the blob container to store files
        """
        
        credential = DefaultAzureCredential()
        account_url = f"https://{storage_account_name}.blob.core.windows.net"
        self.blob_service_client = BlobServiceClient(account_url=account_url, credential=credential)
        self.container_name = container_name
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        
        # Ensure container exists
        try:
            self.blob_service_client.create_container(container_name)
        except Exception as e:
            logger.info(f"Container {container_name} already exists or creation failed: {e}")
    
    def read_urls_from_csv(self, csv_file_path: str) -> List[Tuple[str, str]]:
        """
        Read URLs and filenames from CSV file.
        
        Args:
            csv_file_path: Path to the input CSV file
            
        Returns:
            List of tuples containing (url, filename)
        """
        urls_and_files = []
        try:
            with open(csv_file_path, 'r', encoding='utf-8') as file:
                csv_reader = csv.reader(file)
                next(csv_reader, None)  # Skip header if present
                
                for row in csv_reader:
                    if len(row) >= 2:
                        url = row[0].strip()
                        filename = row[1].strip()
                        if url and filename:
                            urls_and_files.append((url, filename))
                        else:
                            logger.warning(f"Skipping empty row: {row}")
                    else:
                        logger.warning(f"Skipping invalid row: {row}")
                        
        except FileNotFoundError:
            logger.error(f"CSV file not found: {csv_file_path}")
            raise
        except Exception as e:
            logger.error(f"Error reading CSV file: {e}")
            raise
            
        return urls_and_files
    
    def download_page(self, url: str) -> str:
        """
        Download web page content.
        
        Args:
            url: URL to download
            
        Returns:
            HTML content as string
        """
        try:
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            return response.text
        except requests.exceptions.RequestException as e:
            logger.error(f"Error downloading {url}: {e}")
            raise
    
    def upload_to_blob(self, content: str, blob_name: str) -> None:
        """
        Upload content to Azure Blob Storage.
        
        Args:
            content: Content to upload
            blob_name: Name of the blob
        """
        try:
            blob_client = self.blob_service_client.get_blob_client(
                container=self.container_name, 
                blob=blob_name
            )
            blob_client.upload_blob(content, overwrite=True)
            logger.info(f"Successfully uploaded {blob_name} to container {self.container_name}")
        except Exception as e:
            logger.error(f"Error uploading {blob_name}: {e}")
            raise
    
    def save_local(self, content: str, last_path_name: str, filename: str) -> None:
        """
        Save content to local HTML file.
        
        Args:
            content: Content to save
            filename: Name of the file
        """
        html_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'html', last_path_name)
        os.makedirs(html_dir, exist_ok=True)
        file_path = os.path.join(html_dir, filename)
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            logger.info(f"Successfully saved {filename} to {html_dir}")
        except Exception as e:
            logger.error(f"Error saving {filename} locally: {e}")
            raise

    def crawl_and_store(self, csv_file_path: str) -> None:
        """
        Main method to crawl URLs and store in Azure Storage and locally.
        
        Args:
            csv_file_path: Path to the input CSV file
        """
        urls_and_files = self.read_urls_from_csv(csv_file_path)
        
        if not urls_and_files:
            logger.warning("No valid URLs found in CSV file")
            return
        
        logger.info(f"Starting to process {len(urls_and_files)} URLs")
        
        success_count = 0
        for i, (url, filename) in enumerate(urls_and_files, 1):
            try:
                logger.info(f"Processing {i}/{len(urls_and_files)}: {url}")
                
                # Download page content
                content = self.download_page(url)
                
                # Ensure filename has .html extension if not present
                if not filename.lower().endswith(('.html', '.htm')):
                    filename += '.html'
                
                # extract the last path name before the html file from the url. Create the directory with that name and store the file inside it.
                last_path_name = url.rstrip('/').split('/')[-2]
               
                
                # Upload to Azure Storage and save locally
                #self.upload_to_blob(content, filename)
                self.save_local(content, last_path_name, filename)
                success_count += 1
                
            except Exception as e:
                logger.error(f"Failed to process {url}: {e}")
                continue
        
        logger.info(f"Completed processing. {success_count}/{len(urls_and_files)} files uploaded successfully")

def main():
    # Configuration - replace with your actual values
    STORAGE_ACCOUNT_NAME = os.getenv('AZURE_STORAGE_ACCOUNT_NAME')
    CONTAINER_NAME = os.getenv('AZURE_STORAGE_CONTAINER_NAME', 'webpages')
    CSV_FILE_PATH = 'input.csv'
    
    if not STORAGE_ACCOUNT_NAME:
        logger.error("AZURE_STORAGE_ACCOUNT_NAME environment variable not set")
        return
    
    try:
        crawler = WebPageCrawler(STORAGE_ACCOUNT_NAME, CONTAINER_NAME)
        crawler.crawl_and_store(CSV_FILE_PATH)
    except Exception as e:
        logger.error(f"Crawling failed: {e}")

if __name__ == "__main__":
    main()
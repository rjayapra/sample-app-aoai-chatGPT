import csv
import json
from urllib.parse import urljoin
from pathlib import Path
import os

def get_common_prefix_and_paths():
    # Read the CSV file
    urls = []
    with open('input.csv', 'r', encoding='utf-8') as f:
        csv_reader = csv.DictReader(f)
        for row in csv_reader:
            url = next(iter(row.values()))
            urls.append(url)
    
    if not urls:
        return None, []
    
    # Find the common prefix
    url_parts = [url.split('/') for url in urls]
    min_length = min(len(parts) for parts in url_parts)
    
    common_prefix_parts = []
    for i in range(min_length):
        if all(parts[i] == url_parts[0][i] for parts in url_parts):
            common_prefix_parts.append(url_parts[0][i])
        else:
            break
    
    # Get the common prefix
    common_prefix = '/'.join(common_prefix_parts) + '/'
    
    # Get the URLs and filenames
    url_file_pairs = []
    for url in urls:
        filename = url.split('/')[-1]  # Get the last part of the URL (the filename)
        url_prefix = url[:-len(filename)]  # Get everything except the filename
        if filename:
            url_file_pairs.append((url_prefix, filename))
    
    return url_file_pairs

def update_config():
    # Get URL-filename pairs
    url_file_pairs = get_common_prefix_and_paths()
    
    if not url_file_pairs:
        print("No URLs found in input.csv")
        return
    
    # Read the current config
    with open('config_oscar.json', 'r', encoding='utf-8') as f:
        config = json.load(f)
    
    # Create individual entries for each file
    data_paths = []
    for url_prefix, filename in url_file_pairs:
        data_paths.append({
            "path": f"data/html/{filename}",
            "url_prefix": url_prefix
        })
    
    # Update the config with individual file entries
    config[0]['data_paths'] = data_paths
    
    # Write the updated config
    with open('config_oscar.json', 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=4)

if __name__ == "__main__":
    update_config()
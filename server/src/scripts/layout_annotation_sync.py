"""
Layout Annotation Sync — Upload/download batches between BEn-app and eXist-db.

Usage:
  # Upload a YOLO dataset (images + predictions) to eXist-db for collaborative correction
  python layout_annotation_sync.py upload \
    --dataset CAD_A1 \
    --source /path/to/yolo/dataset \
    --exist-url https://your-exist-server.com/exist/apps/LAD \
    --token YOUR_BEARER_TOKEN

  # Download corrected annotations back to YOLO format
  python layout_annotation_sync.py download \
    --dataset CAD_A1 \
    --output /path/to/output \
    --exist-url https://your-exist-server.com/exist/apps/LAD \
    --token YOUR_BEARER_TOKEN

  # Upload from BEn-app's page collection (auto-finds images by parent_id)
  python layout_annotation_sync.py upload-pages \
    --collections A-1_dijzer B_m6gco2 D_lqwq49 \
    --dataset CAD_batch1 \
    --classes entry subentry \
    --predictions /path/to/yolo/predictions \
    --exist-url https://your-exist-server.com/exist/apps/LAD \
    --token YOUR_BEARER_TOKEN
"""

import argparse
import base64
import json
import os
import sys
import time
import requests
from pathlib import Path


def get_headers(token):
    return {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    }


def api_call(base_url, params, token, method='GET', body=None):
    url = f"{base_url}/modules/api/layout-annotations.xql"
    headers = get_headers(token)
    if method == 'GET':
        resp = requests.get(url, params=params, headers=headers)
    elif method == 'POST':
        resp = requests.post(url, params=params, headers=headers, json=body)
    elif method == 'PUT':
        resp = requests.put(url, params=params, headers=headers, json=body)
    else:
        raise ValueError(f"Unknown method: {method}")

    resp.raise_for_status()
    return resp.json()


# ============== CREATE DATASET ==============

def create_dataset(base_url, token, name, classes, class_colors=None):
    """Create a dataset with class definitions."""
    default_colors = [
        '#0000FF', '#00FFFF', '#808080', '#FF0000', '#00FF00',
        '#FFFF00', '#FF00FF', '#FF8000', '#8000FF', '#0080FF'
    ]
    class_list = []
    for i, cls_name in enumerate(classes):
        color = (class_colors or {}).get(cls_name, default_colors[i % len(default_colors)])
        class_list.append({'id': i, 'name': cls_name, 'color': color})

    result = api_call(base_url, {'action': 'create-dataset'}, token, 'POST', {
        'name': name,
        'classes': class_list
    })
    print(f"Dataset '{name}' created: {result.get('message', '')}")
    return result


# ============== UPLOAD ==============

def upload_image(base_url, token, dataset, image_id, image_path, annotations=None, filename=None, split='train'):
    """Upload a single image + optional predictions."""
    with open(image_path, 'rb') as f:
        image_b64 = base64.b64encode(f.read()).decode('utf-8')

    ext = Path(image_path).suffix.lstrip('.')
    body = {
        'image_id': image_id,
        'filename': filename or Path(image_path).name,
        'image_base64': image_b64,
        'extension': ext,
        'annotations': annotations or [],
        'split': split
    }

    result = api_call(base_url, {'action': 'upload-image', 'dataset': dataset}, token, 'POST', body)
    return result


def parse_yolo_label(label_path, class_names=None):
    """Parse a YOLO .txt label file into annotation dicts."""
    annotations = []
    if not os.path.exists(label_path):
        return annotations

    with open(label_path, 'r') as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) >= 5:
                annotations.append({
                    'class_id': int(parts[0]),
                    'x_center': float(parts[1]),
                    'y_center': float(parts[2]),
                    'width': float(parts[3]),
                    'height': float(parts[4])
                })
    return annotations


def upload_yolo_dataset(base_url, token, dataset_name, source_dir, classes=None):
    """Upload a YOLO-format dataset directory."""
    source = Path(source_dir)

    # Read dataset.yaml or metadata.json for classes
    if classes is None:
        meta_path = source / 'metadata.json'
        if meta_path.exists():
            with open(meta_path) as f:
                meta = json.load(f)
                classes = [c['name'] for c in meta.get('classes', [])]

        yaml_path = source / 'dataset.yaml'
        if not classes and yaml_path.exists():
            import yaml
            with open(yaml_path) as f:
                cfg = yaml.safe_load(f)
                classes = cfg.get('names', [])

    if not classes:
        print("ERROR: No classes found. Provide --classes or ensure dataset has metadata.")
        return

    # Create dataset
    create_dataset(base_url, token, dataset_name, classes)

    # Find images (train + val)
    uploaded = 0
    for split in ['train', 'val']:
        img_dir = source / 'images' / split
        lbl_dir = source / 'labels' / split
        if not img_dir.exists():
            continue

        for img_file in sorted(img_dir.iterdir()):
            if img_file.suffix.lower() not in ('.png', '.jpg', '.jpeg'):
                continue

            image_id = img_file.stem
            label_file = lbl_dir / f"{image_id}.txt"
            annotations = parse_yolo_label(label_file)

            print(f"  Uploading {img_file.name} ({len(annotations)} annotations)...")
            try:
                upload_image(base_url, token, dataset_name, image_id, str(img_file), annotations, split=split)
                uploaded += 1
            except Exception as e:
                print(f"  ERROR uploading {img_file.name}: {e}")

            # Rate limit to avoid overwhelming eXist-db
            if uploaded % 10 == 0:
                time.sleep(0.5)

    print(f"\nDone! Uploaded {uploaded} images to dataset '{dataset_name}'.")


def upload_page_collections(base_url, token, dataset_name, collection_ids, classes,
                            predictions_dir=None, pages_base=None):
    """Upload from BEn-app page collections with optional YOLO predictions."""
    if pages_base is None:
        # Default BEn-app pages path
        pages_base = Path(__file__).parent.parent / 'data' / 'pages'

    class_colors = {'entry': '#0000FF', 'subentry': '#00FFFF', 'guidewords': '#808080'}
    create_dataset(base_url, token, dataset_name, classes, class_colors)

    uploaded = 0
    for coll_id in collection_ids:
        coll_dir = pages_base / coll_id
        if not coll_dir.exists():
            # Try to find by prefix
            matches = list(pages_base.glob(f"{coll_id}*"))
            if matches:
                coll_dir = matches[0]
            else:
                print(f"  Collection '{coll_id}' not found, skipping.")
                continue

        print(f"\nProcessing collection: {coll_dir.name}")

        for img_file in sorted(coll_dir.glob('*.png')):
            image_id = f"{coll_dir.name}_{img_file.stem}"
            annotations = []

            # Check for predictions
            if predictions_dir:
                pred_file = Path(predictions_dir) / f"{img_file.stem}.txt"
                if not pred_file.exists():
                    # Try with collection prefix
                    pred_file = Path(predictions_dir) / f"{image_id}.txt"
                annotations = parse_yolo_label(pred_file)

            print(f"  {img_file.name} ({len(annotations)} predictions)...")
            try:
                upload_image(base_url, token, dataset_name, image_id, str(img_file),
                             annotations, filename=img_file.name)
                uploaded += 1
            except Exception as e:
                print(f"  ERROR: {e}")

            if uploaded % 10 == 0:
                time.sleep(0.5)

    print(f"\nDone! Uploaded {uploaded} images to dataset '{dataset_name}'.")


# ============== DOWNLOAD ==============

def download_annotations(base_url, token, dataset_name, output_dir, curated_only=False):
    """Download corrected annotations back to YOLO .txt format, preserving train/val split."""
    output = Path(output_dir)

    # Create split-aware directory structure
    for split in ['train', 'val']:
        (output / 'labels' / split).mkdir(parents=True, exist_ok=True)

    # Get image list
    data = api_call(base_url, {'action': 'list-images', 'dataset': dataset_name}, token)
    images = data.get('images', [])

    if curated_only:
        images = [img for img in images if img.get('curated')]

    print(f"Downloading {len(images)} {'curated ' if curated_only else ''}annotations...")

    downloaded = 0
    split_counts = {'train': 0, 'val': 0}
    for img in images:
        image_id = img['image_id']
        img_data = api_call(base_url, {
            'action': 'get-image', 'dataset': dataset_name, 'image_id': image_id
        }, token)

        annotations = img_data.get('annotations', [])
        split = img_data.get('split', 'train')
        split_counts[split] = split_counts.get(split, 0) + 1
        label_file = output / 'labels' / split / f"{image_id}.txt"

        with open(label_file, 'w') as f:
            for ann in annotations:
                f.write(f"{ann['class_id']} {ann['x_center']:.6f} {ann['y_center']:.6f} "
                        f"{ann['width']:.6f} {ann['height']:.6f}\n")

        downloaded += 1
        if downloaded % 20 == 0:
            print(f"  {downloaded}/{len(images)}...")

    # Also save metadata
    meta = api_call(base_url, {'action': 'get-dataset', 'dataset': dataset_name}, token)
    with open(output / 'metadata.json', 'w') as f:
        json.dump(meta, f, indent=2)

    # Write classes file
    classes = meta.get('classes', [])
    with open(output / 'classes.txt', 'w') as f:
        for cls in sorted(classes, key=lambda c: c['id']):
            f.write(f"{cls['name']}\n")

    print(f"\nDone! Downloaded {downloaded} label files to {labels_dir}")
    print(f"Classes: {', '.join(c['name'] for c in classes)}")


# ============== CLI ==============

def main():
    parser = argparse.ArgumentParser(description='Layout Annotation Sync')
    parser.add_argument('--exist-url', required=True, help='eXist-db app URL (e.g. https://server/exist/apps/LAD)')
    parser.add_argument('--token', required=True, help='Bearer auth token')

    subparsers = parser.add_subparsers(dest='command')

    # Upload YOLO dataset
    up = subparsers.add_parser('upload', help='Upload YOLO dataset')
    up.add_argument('--dataset', required=True, help='Dataset name')
    up.add_argument('--source', required=True, help='YOLO dataset directory')
    up.add_argument('--classes', nargs='+', help='Class names (if not in metadata)')

    # Upload from page collections
    up_pages = subparsers.add_parser('upload-pages', help='Upload from BEn-app page collections')
    up_pages.add_argument('--dataset', required=True, help='Dataset name')
    up_pages.add_argument('--collections', nargs='+', required=True, help='Collection folder names')
    up_pages.add_argument('--classes', nargs='+', default=['entry', 'subentry'], help='Class names')
    up_pages.add_argument('--predictions', help='Directory with YOLO .txt prediction files')
    up_pages.add_argument('--pages-base', help='Base path for page collections')

    # Download
    dl = subparsers.add_parser('download', help='Download corrected annotations')
    dl.add_argument('--dataset', required=True, help='Dataset name')
    dl.add_argument('--output', required=True, help='Output directory')
    dl.add_argument('--curated-only', action='store_true', help='Only download curated images')

    args = parser.parse_args()

    if args.command == 'upload':
        upload_yolo_dataset(args.exist_url, args.token, args.dataset, args.source, args.classes)
    elif args.command == 'upload-pages':
        upload_page_collections(
            args.exist_url, args.token, args.dataset,
            args.collections, args.classes,
            args.predictions, args.pages_base
        )
    elif args.command == 'download':
        download_annotations(args.exist_url, args.token, args.dataset, args.output, args.curated_only)
    else:
        parser.print_help()


if __name__ == '__main__':
    main()

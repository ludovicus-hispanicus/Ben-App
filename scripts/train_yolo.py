"""
Train YOLOv8 model on dictionary layout dataset.

Usage:
    python train_yolo.py [--epochs EPOCHS] [--batch BATCH] [--imgsz IMGSZ] [--model MODEL]

Example:
    python train_yolo.py --epochs 100 --batch 4 --imgsz 1024

Settings optimized for 8GB GPU:
    - Model: yolov8s (small) - fits comfortably
    - Batch size: 4
    - Image size: 1024 (dictionary pages need high resolution)
"""

import argparse
import os
import sys

from ultralytics import YOLO


def main():
    parser = argparse.ArgumentParser(description="Train YOLOv8 on dictionary layout dataset")
    parser.add_argument("--data", default="yolo_dataset/dataset.yaml",
                        help="Path to dataset.yaml")
    parser.add_argument("--model", default="yolov8s.pt",
                        help="Pre-trained model (yolov8n/s/m/l/x.pt)")
    parser.add_argument("--epochs", type=int, default=100,
                        help="Number of training epochs")
    parser.add_argument("--batch", type=int, default=4,
                        help="Batch size (reduce if OOM)")
    parser.add_argument("--imgsz", type=int, default=1024,
                        help="Image size for training")
    parser.add_argument("--patience", type=int, default=20,
                        help="Early stopping patience")
    parser.add_argument("--device", default="0",
                        help="Device: 0 for GPU, cpu for CPU")
    parser.add_argument("--resume", action="store_true",
                        help="Resume training from last checkpoint")
    parser.add_argument("--workers", type=int, default=4,
                        help="Number of data loader workers")
    args = parser.parse_args()

    # Check dataset exists
    if not os.path.exists(args.data):
        print(f"Error: Dataset config not found: {args.data}")
        print("Run prepare_yolo_data.py first to create the dataset.")
        sys.exit(1)

    # Check for training images
    train_images_dir = os.path.join(os.path.dirname(args.data), "images", "train")
    if not os.path.exists(train_images_dir) or not os.listdir(train_images_dir):
        print(f"Error: No training images found in: {train_images_dir}")
        sys.exit(1)

    num_images = len([f for f in os.listdir(train_images_dir) if f.endswith(('.png', '.jpg'))])
    print(f"Found {num_images} training images")

    # Check for validation images (warn if empty)
    val_images_dir = os.path.join(os.path.dirname(args.data), "images", "val")
    if not os.path.exists(val_images_dir) or not os.listdir(val_images_dir):
        print("Warning: No validation images found. Training will use train set for validation.")
        print("Consider copying some images to val/ for proper validation.")

    # Load model
    print(f"\nLoading model: {args.model}")
    model = YOLO(args.model)

    # Training settings
    print(f"\nTraining configuration:")
    print(f"  Dataset: {args.data}")
    print(f"  Model: {args.model}")
    print(f"  Epochs: {args.epochs}")
    print(f"  Batch size: {args.batch}")
    print(f"  Image size: {args.imgsz}")
    print(f"  Patience: {args.patience}")
    print(f"  Device: {args.device}")
    print(f"  Workers: {args.workers}")

    # Train
    print("\n" + "="*50)
    print("Starting training...")
    print("="*50 + "\n")

    results = model.train(
        data=args.data,
        epochs=args.epochs,
        batch=args.batch,
        imgsz=args.imgsz,
        patience=args.patience,
        device=args.device,
        workers=args.workers,
        resume=args.resume,
        # Augmentation settings for document images
        hsv_h=0.0,  # No hue augmentation (documents are usually grayscale/sepia)
        hsv_s=0.1,  # Low saturation augmentation
        hsv_v=0.2,  # Some brightness variation
        degrees=0.5,  # Very slight rotation (documents are mostly straight)
        translate=0.1,  # Slight translation
        scale=0.2,  # Some scale variation
        flipud=0.0,  # No vertical flip (text would be upside down)
        fliplr=0.0,  # No horizontal flip (text would be mirrored)
        mosaic=0.0,  # Disable mosaic (not suitable for document layout)
        # Saving
        save=True,
        save_period=10,  # Save checkpoint every 10 epochs
        project="runs/detect",
        name="dictionary_layout",
        exist_ok=True,
    )

    print("\n" + "="*50)
    print("Training complete!")
    print("="*50)

    # Print results location
    print(f"\nResults saved to: runs/detect/dictionary_layout/")
    print(f"Best model: runs/detect/dictionary_layout/weights/best.pt")
    print(f"Last model: runs/detect/dictionary_layout/weights/last.pt")
    print(f"\nTo run inference:")
    print(f"  python predict_layout.py <pdf_path> [first_page] [last_page]")


if __name__ == "__main__":
    main()

"""
CuRe Dataset — PyTorch Dataset for cuneiform sign classification training.

Adapted from CuneiformOcr/src/dataset.py.
Loads pre-extracted 64x64 sign crops organized in label subdirectories.
"""
import logging
import os
from typing import Dict, List, Tuple

import numpy as np
from PIL import Image
from sklearn.model_selection import train_test_split
from torch.utils.data import Dataset, DataLoader, random_split
import torchvision.transforms as transforms


class CuReDataset(Dataset):
    """PyTorch Dataset for cuneiform sign classification."""

    def __init__(
        self,
        samples: List[Tuple[str, int]],
        transform=None,
        image_size: int = 64,
    ):
        """
        Args:
            samples: List of (image_path, label_index) tuples
            transform: torchvision transforms to apply
            image_size: Target image size (default 64x64)
        """
        self.samples = samples
        self.transform = transform
        self.image_size = image_size

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, index):
        import torch

        image_path, label_idx = self.samples[index]

        image = Image.open(image_path).convert("RGB")
        image = image.resize((self.image_size, self.image_size))

        # Normalize to [0, 1] float64 (matching original CuneiformOcr)
        image_np = np.asarray(image).reshape(
            self.image_size, self.image_size, 3
        ).astype(np.float64) / 255.0

        if self.transform:
            image_tensor = self.transform(image_np)
        else:
            image_tensor = transforms.ToTensor()(image_np)

        label_tensor = torch.tensor(label_idx)
        return image_tensor, label_tensor


def load_crops_from_directory(
    crops_dir: str, label_to_index: Dict[str, int]
) -> List[Tuple[str, int]]:
    """
    Load samples from a directory organized as:
        crops_dir/
            LABEL_NAME/
                crop_001.png
                crop_002.png
            ...

    Returns:
        List of (image_path, label_index) tuples.
    """
    samples = []
    unknown_labels = set()

    for label_name in os.listdir(crops_dir):
        label_path = os.path.join(crops_dir, label_name)
        if not os.path.isdir(label_path):
            continue

        if label_name not in label_to_index:
            unknown_labels.add(label_name)
            continue

        label_idx = label_to_index[label_name]
        for filename in os.listdir(label_path):
            if filename.lower().endswith((".png", ".jpg", ".jpeg")):
                samples.append((os.path.join(label_path, filename), label_idx))

    if unknown_labels:
        logging.warning(f"CuRe dataset: {len(unknown_labels)} unknown labels skipped: {unknown_labels}")

    logging.info(f"CuRe dataset: loaded {len(samples)} samples from {crops_dir}")
    return samples


def create_data_loaders(
    crops_dir: str,
    label_to_index: Dict[str, int],
    batch_size: int = 256,
    test_ratio: float = 0.36,
    val_ratio: float = 0.4,
) -> Tuple[DataLoader, DataLoader, DataLoader, List[str]]:
    """
    Create train/val/test DataLoaders from crop directory.

    Split ratios (matching original CuneiformOcr):
        - Train: 64%
        - Validation: 14.4% (36% * 40%)
        - Test: 21.6% (36% * 60%)

    Returns:
        (train_loader, val_loader, test_loader, label_list)
    """
    samples = load_crops_from_directory(crops_dir, label_to_index)

    if not samples:
        raise ValueError(f"No training samples found in {crops_dir}")

    # Split into train and test+val
    paths = [s[0] for s in samples]
    labels = [s[1] for s in samples]
    train_paths, test_paths, train_labels, test_labels = train_test_split(
        paths, labels, test_size=test_ratio, random_state=42, stratify=labels if len(set(labels)) > 1 else None
    )

    train_samples = list(zip(train_paths, train_labels))
    test_val_samples = list(zip(test_paths, test_labels))

    # Augmentation for training (matching original CuneiformOcr)
    train_transform = transforms.Compose([
        transforms.ToTensor(),
        transforms.RandomAffine(degrees=3),
        transforms.RandomAffine(degrees=4),
    ])
    eval_transform = transforms.Compose([transforms.ToTensor()])

    train_dataset = CuReDataset(train_samples, transform=train_transform)
    test_val_dataset = CuReDataset(test_val_samples, transform=eval_transform)

    # Split test+val into val and test
    val_len = int(val_ratio * len(test_val_dataset))
    test_len = len(test_val_dataset) - val_len
    val_dataset, test_dataset = random_split(test_val_dataset, [val_len, test_len])

    train_loader = DataLoader(train_dataset, batch_size=batch_size, shuffle=True)
    val_loader = DataLoader(val_dataset, batch_size=128, shuffle=False)
    test_loader = DataLoader(test_dataset, batch_size=128, shuffle=False)

    label_list = sorted(label_to_index.keys(), key=lambda k: label_to_index[k])

    logging.info(
        f"CuRe data loaders created: "
        f"train={len(train_dataset)}, val={val_len}, test={test_len}, "
        f"classes={len(label_list)}"
    )
    return train_loader, val_loader, test_loader, label_list

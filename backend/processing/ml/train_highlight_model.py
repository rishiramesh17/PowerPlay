"""
Minimal training script for a highlight classifier using the clips captured via
capture_segments_to_dataset. Expects a labels.jsonl file with labeled rows
under data/highlight_dataset/, each row:
  {"clip_path": ".../clip.mp4", "label": "boundary", "start": ..., "end": ..., "meta": {...}}

Usage (example):
  python backend/processing/ml/train_highlight_model.py \
    --data-root data/highlight_dataset \
    --epochs 5 \
    --batch-size 8 \
    --num-frames 8
"""

import argparse
import json
import logging
import random
from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict, Any, Tuple

import cv2
import torch
import torch.nn as nn
import torch.optim as optim
from PIL import Image
from torch.utils.data import Dataset, DataLoader
from torchvision import transforms, models
from torchvision.models import ResNet18_Weights

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("highlight_trainer")


# --------------------------------------------------------------------------- #
# Data loading
# --------------------------------------------------------------------------- #
@dataclass
class ClipSample:
    path: Path
    label: str
    meta: Dict[str, Any]


def load_labels(labels_path: Path) -> List[ClipSample]:
    samples: List[ClipSample] = []
    if not labels_path.exists():
        raise FileNotFoundError(f"labels file not found: {labels_path}")
    with labels_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            label = row.get("label")
            clip_path = row.get("clip_path")
            if not label or label is None:
                continue
            if not clip_path:
                continue
            clip_path = Path(clip_path)
            if not clip_path.exists():
                continue
            samples.append(ClipSample(path=clip_path, label=str(label), meta=row.get("meta", {})))
    return samples


class HighlightDataset(Dataset):
    def __init__(self, samples: List[ClipSample], label_to_idx: Dict[str, int], num_frames: int = 8, img_size: int = 224):
        self.samples = samples
        self.label_to_idx = label_to_idx
        self.num_frames = num_frames
        self.transform = transforms.Compose([
            transforms.Resize((img_size, img_size)),
            transforms.ToTensor(),
            transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
        ])

    def __len__(self) -> int:
        return len(self.samples)

    def _sample_frames(self, video_path: Path) -> torch.Tensor:
        cap = cv2.VideoCapture(str(video_path))
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 1)
        # uniform frame indices
        idxs = [int(i * total_frames / self.num_frames + total_frames / (2 * self.num_frames)) for i in range(self.num_frames)]
        frames = []
        for idx in idxs:
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ok, frame = cap.read()
            if not ok or frame is None:
                continue
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            img = Image.fromarray(frame)
            frames.append(self.transform(img))
        cap.release()

        if not frames:
            # fallback black frames
            frames = [torch.zeros(3, self.transform.transforms[0].size[0], self.transform.transforms[0].size[1])] * self.num_frames

        # pad if needed
        while len(frames) < self.num_frames:
            frames.append(frames[-1])

        return torch.stack(frames[:self.num_frames], dim=0)  # [T,3,H,W]

    def __getitem__(self, idx: int) -> Tuple[torch.Tensor, int]:
        sample = self.samples[idx]
        frames = self._sample_frames(sample.path)
        label_idx = self.label_to_idx[sample.label]
        return frames, label_idx


def split_dataset(samples: List[ClipSample], val_split: float, test_split: float, seed: int = 42):
    random.Random(seed).shuffle(samples)
    n = len(samples)
    n_val = int(n * val_split)
    n_test = int(n * test_split)
    val = samples[:n_val]
    test = samples[n_val:n_val + n_test]
    train = samples[n_val + n_test:]
    return train, val, test


# --------------------------------------------------------------------------- #
# Model
# --------------------------------------------------------------------------- #
class FramePoolClassifier(nn.Module):
    def __init__(self, num_classes: int, pretrained: bool = True):
        super().__init__()
        weights = ResNet18_Weights.IMAGENET1K_V1 if pretrained else None
        base = models.resnet18(weights=weights)
        self.encoder = nn.Sequential(*list(base.children())[:-1])  # drop fc, keep pooling
        self.head = nn.Linear(base.fc.in_features, num_classes)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: [B, T, 3, H, W]
        b, t, c, h, w = x.shape
        x = x.view(b * t, c, h, w)
        feats = self.encoder(x)  # [b*t, C, 1, 1]
        feats = feats.view(b, t, -1)
        pooled = feats.mean(dim=1)
        return self.head(pooled)


# --------------------------------------------------------------------------- #
# Training loop
# --------------------------------------------------------------------------- #
def train_one_epoch(model, loader, device, optimizer, criterion):
    model.train()
    total, correct, loss_sum = 0, 0, 0.0
    for frames, labels in loader:
        frames = frames.to(device)
        labels = labels.to(device)

        optimizer.zero_grad()
        logits = model(frames)
        loss = criterion(logits, labels)
        loss.backward()
        optimizer.step()

        loss_sum += loss.item() * labels.size(0)
        preds = logits.argmax(dim=1)
        correct += (preds == labels).sum().item()
        total += labels.size(0)
    acc = correct / max(1, total)
    return loss_sum / max(1, total), acc


@torch.no_grad()
def eval_model(model, loader, device, criterion):
    model.eval()
    total, correct, loss_sum = 0, 0, 0.0
    for frames, labels in loader:
        frames = frames.to(device)
        labels = labels.to(device)
        logits = model(frames)
        loss = criterion(logits, labels)
        loss_sum += loss.item() * labels.size(0)
        preds = logits.argmax(dim=1)
        correct += (preds == labels).sum().item()
        total += labels.size(0)
    acc = correct / max(1, total)
    return loss_sum / max(1, total), acc


def main():
    parser = argparse.ArgumentParser(description="Train highlight classifier from captured clips.")
    parser.add_argument("--data-root", type=Path, default=Path("data/highlight_dataset"), help="Root containing clips/ and labels.jsonl")
    parser.add_argument("--labels-file", type=Path, default=None, help="Path to labels.jsonl (defaults to data-root/labels.jsonl)")
    parser.add_argument("--epochs", type=int, default=5)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--num-frames", type=int, default=8)
    parser.add_argument("--img-size", type=int, default=224)
    parser.add_argument("--lr", type=float, default=1e-4)
    parser.add_argument("--weight-decay", type=float, default=1e-2)
    parser.add_argument("--val-split", type=float, default=0.1)
    parser.add_argument("--test-split", type=float, default=0.1)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", type=Path, default=Path("backend/models/highlight_classifier.pt"))
    parser.add_argument("--no-pretrained", action="store_true", help="Disable ImageNet weights")
    args = parser.parse_args()

    labels_file = args.labels_file or (args.data_root / "labels.jsonl")
    samples = load_labels(labels_file)
    if len(samples) < 4:
        raise RuntimeError("Not enough labeled clips. Label more entries in labels.jsonl.")

    # build label map
    labels = sorted({s.label for s in samples})
    label_to_idx = {lbl: i for i, lbl in enumerate(labels)}
    idx_to_label = {i: lbl for lbl, i in label_to_idx.items()}

    train_samples, val_samples, test_samples = split_dataset(samples, args.val_split, args.test_split, seed=args.seed)
    logger.info(f"Dataset sizes -> train: {len(train_samples)} | val: {len(val_samples)} | test: {len(test_samples)}")
    if len(train_samples) == 0 or len(val_samples) == 0:
        raise RuntimeError("Split resulted in empty train/val set. Add more data or adjust splits.")

    train_ds = HighlightDataset(train_samples, label_to_idx, num_frames=args.num_frames, img_size=args.img_size)
    val_ds = HighlightDataset(val_samples, label_to_idx, num_frames=args.num_frames, img_size=args.img_size)
    test_ds = HighlightDataset(test_samples, label_to_idx, num_frames=args.num_frames, img_size=args.img_size)

    train_loader = DataLoader(train_ds, batch_size=args.batch_size, shuffle=True, num_workers=2, pin_memory=True)
    val_loader = DataLoader(val_ds, batch_size=args.batch_size, shuffle=False, num_workers=2, pin_memory=True)
    test_loader = DataLoader(test_ds, batch_size=args.batch_size, shuffle=False, num_workers=2, pin_memory=True)

    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = FramePoolClassifier(num_classes=len(label_to_idx), pretrained=not args.no_pretrained).to(device)
    criterion = nn.CrossEntropyLoss()
    optimizer = optim.AdamW(model.parameters(), lr=args.lr, weight_decay=args.weight_decay)

    best_val = 0.0
    for epoch in range(1, args.epochs + 1):
        train_loss, train_acc = train_one_epoch(model, train_loader, device, optimizer, criterion)
        val_loss, val_acc = eval_model(model, val_loader, device, criterion)
        logger.info(f"Epoch {epoch}: train loss {train_loss:.4f} acc {train_acc:.3f} | val loss {val_loss:.4f} acc {val_acc:.3f}")
        if val_acc > best_val:
            best_val = val_acc
            save_payload = {
                "state_dict": model.state_dict(),
                "label_to_idx": label_to_idx,
                "idx_to_label": idx_to_label,
                "num_frames": args.num_frames,
                "img_size": args.img_size,
            }
            args.output.parent.mkdir(parents=True, exist_ok=True)
            torch.save(save_payload, args.output)
            logger.info(f"💾 Saved checkpoint to {args.output}")

    # final test eval
    test_loss, test_acc = eval_model(model, test_loader, device, criterion)
    logger.info(f"Test loss {test_loss:.4f} acc {test_acc:.3f}")


if __name__ == "__main__":
    main()


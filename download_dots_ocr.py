"""
Download the repackaged dots.ocr model to a local directory with clean name.
"""
import os
import sys
from pathlib import Path

def main():
    print("=" * 60)
    print("Downloading dots.ocr (prithivMLmods repackage)")
    print("=" * 60)

    # Create local model directory (no periods!)
    model_dir = Path("./models/DotsOCR_BF16")
    model_dir.mkdir(parents=True, exist_ok=True)
    print(f"Target directory: {model_dir.absolute()}")

    try:
        from huggingface_hub import snapshot_download

        # Download to local directory with clean name
        local_path = snapshot_download(
            repo_id="prithivMLmods/Dots.OCR-Latest-BF16",
            local_dir=str(model_dir),
            local_dir_use_symlinks=False,  # Important for Windows
            ignore_patterns=["*.md", "*.txt", ".git*"]
        )

        print(f"\nModel downloaded to: {local_path}")

        # List files
        print("\nFiles downloaded:")
        for f in sorted(model_dir.glob("*")):
            if f.is_file():
                size_mb = f.stat().st_size / 1024 / 1024
                print(f"  {f.name}: {size_mb:.1f} MB")

        print("\n" + "=" * 60)
        print("DOWNLOAD COMPLETE!")
        print("=" * 60)
        return True

    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)

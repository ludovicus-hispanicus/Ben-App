"""
Wrapper script for running ketos with patches for known bugs:
1. Rich library: 'pop from empty list' error in subprocess environments
2. Kraken lineest: inhomogeneous array in dewarping (numpy compatibility)
"""
import sys

# Patch rich before any imports that might use it
def _patch_rich():
    """Patch rich.Console.clear_live to not crash on empty stack."""
    try:
        from rich.console import Console

        _original_clear_live = Console.clear_live

        def _safe_clear_live(self):
            """Safe version of clear_live that handles empty stack or missing attributes."""
            try:
                _original_clear_live(self)
            except (IndexError, AttributeError):
                pass  # Empty stack or missing _live_stack — safe to ignore

        Console.clear_live = _safe_clear_live
    except ImportError:
        pass  # rich not installed

def _patch_lineest():
    """
    Patch kraken.lib.lineest.CenterNormalizer.dewarp to handle
    inhomogeneous column lengths that crash numpy.

    The bug: when center[i]-self.r < 0, numpy clips the slice start to 0,
    producing a shorter column. np.array() then fails because columns have
    different lengths.

    The fix: pad each column to exactly 2*self.r elements.
    """
    try:
        from kraken.lib.lineest import CenterNormalizer
        import numpy as np

        def _safe_dewarp(self, img, cval=0, dtype=np.dtype('f')):
            if img.shape != self.shape:
                raise Exception('Measured and dewarp image shapes different')
            h, w = img.shape
            padded = np.vstack([cval * np.ones((h, w)), img, cval * np.ones((h, w))])
            center = self.center + h
            target_len = 2 * self.r
            dewarped = []
            for i in range(w):
                start = center[i] - self.r
                end = center[i] + self.r
                col = padded[max(0, start):end, i]
                # Pad if column is too short (start was clipped to 0)
                if len(col) < target_len:
                    pad_amount = target_len - len(col)
                    col = np.pad(col, (pad_amount, 0), constant_values=cval)
                dewarped.append(col)
            dewarped = np.array(dewarped, dtype=dtype).T
            return dewarped

        CenterNormalizer.dewarp = _safe_dewarp
    except ImportError:
        pass  # kraken not installed

_patch_rich()
_patch_lineest()

# Now run ketos CLI
if __name__ == "__main__":
    from kraken.ketos import cli
    sys.exit(cli())

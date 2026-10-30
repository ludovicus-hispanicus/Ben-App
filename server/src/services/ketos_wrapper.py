"""
Wrapper script for running ketos (kraken 7.x; also tolerant of kraken 6.x)
with patches for known problems when it runs as a BEn subprocess:
1. Console encoding: on Windows the subprocess stdout/stderr default to the
   ANSI code page; ketos prints training alphabets (subscript digits, ḫ, ...)
   through rich, which then dies with UnicodeEncodeError. Force UTF-8.
2. Rich library: 'pop from empty list' error in subprocess environments.
3. Kraken lineest: inhomogeneous array in dewarping (numpy compatibility)
   for legacy VGSL models.
"""
import sys


def _force_utf8_streams():
    """Reconfigure stdout/stderr to UTF-8 so non-Latin-1 output never crashes."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


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
    except (ImportError, AttributeError):
        pass  # kraken not installed or lineest layout changed


def main(args=None) -> int:
    """Run the ketos CLI with the patches applied.

    ``args`` are the ketos arguments (default: the command line). The installed
    app has no Python, so cured-server.exe calls this for ``--ketos ...``
    (see run_server.py).
    """
    _force_utf8_streams()
    _patch_rich()
    _patch_lineest()
    # kraken 7: kraken.ketos.cli is the click group; same import on 6.x
    from kraken.ketos import cli
    return cli.main(args=args, prog_name="ketos", standalone_mode=True)


if __name__ == "__main__":
    sys.exit(main())

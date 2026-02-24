"""
Wrapper script for running ketos with rich library patched to avoid
the 'pop from empty list' error in subprocess environments.

This patches rich.Console.clear_live to handle empty live_stack gracefully.
"""
import sys

# Patch rich before any imports that might use it
def _patch_rich():
    """Patch rich.Console.clear_live to not crash on empty stack."""
    try:
        from rich.console import Console

        _original_clear_live = Console.clear_live

        def _safe_clear_live(self):
            """Safe version of clear_live that handles empty stack."""
            with self._lock:
                if self._live_stack:
                    self._live_stack.pop()

        Console.clear_live = _safe_clear_live
    except ImportError:
        pass  # rich not installed

_patch_rich()

# Now run ketos CLI
if __name__ == "__main__":
    from kraken.ketos import cli
    sys.exit(cli())

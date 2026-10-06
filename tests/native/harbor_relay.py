"""Phase 0 compatibility import for the now-shared fixed-upstream relay."""
from magnet_evals.backends.harbor.relay import main, relay

__all__ = ['main', 'relay']

if __name__ == '__main__':
    raise SystemExit(main())

from __future__ import annotations

from sftp_auto_sync.app.bootstrap import bootstrap


def main() -> int:
    return bootstrap()


if __name__ == '__main__':
    raise SystemExit(main())

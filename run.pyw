"""无控制台启动入口。"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lyricdesk.app import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())

"""Allow ``python -m dancing_parrot``."""

import sys

from .cli import main

sys.exit(main())

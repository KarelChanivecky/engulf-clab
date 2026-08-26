"""twine upload with --skip-existing support for our self-hosted repository.

twine's duplicate detection already handles pypiserver (it treats an HTTP 409
response as "already exists"), but twine 7 refuses --skip-existing unless the
repository URL starts with the official PyPI/TestPyPI hosts
(Settings.verify_feature_capability). Our server is a pypiserver, so the
capability is there and only the URL allowlist blocks it. Lift the allowlist
before dispatching to the regular twine CLI; when twine lets third-party
repositories opt into --skip-existing, this wrapper can be deleted.
"""

import os

from twine.__main__ import main as twine_main
from twine.settings import Settings

Settings.verify_feature_capability = lambda self: None  # noqa: E731

# Authentication is configured per-invocation via TWINE_USERNAME/TWINE_PASSWORD;
# without a desktop secret service, keyring probing blocks long enough to look
# hung before twine prompts interactively.
os.environ.setdefault("PYTHON_KEYRING_BACKEND", "keyring.backends.null.Keyring")

if __name__ == "__main__":
    twine_main()

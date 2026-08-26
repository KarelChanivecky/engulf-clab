"""Check whether locally built distributions are hosted on the repository.

Fetches the PEP 503 simple-index project page (pypiserver serves it both at
/<project>/ and /simple/<project>/) and compares the anchor text against the
files in the dist directory. Used by the Makefile to keep the per-package
.published stamp honest without always paying for an upload attempt.

Exit codes: 0 = every built file is hosted; 1 = at least one is missing;
2 = the repository could not be reached/queried.
"""

import os
import re
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path

repository_url, project_name, dist_directory = sys.argv[1:4]

normalized = re.sub(r"[-_.]+", "-", project_name).lower()
context = ssl.create_default_context(cafile=os.environ.get("TWINE_CERT") or None)
if os.environ.get("TWINE_CLIENT_CERT"):
    context.load_cert_chain(os.environ["TWINE_CLIENT_CERT"])

artifacts = [
    entry.name
    for entry in Path(dist_directory).iterdir()
    if entry.suffix == ".whl" or entry.name.endswith(".tar.gz")
]


def fetch_project_page(url: str) -> str | None:
    try:
        with urllib.request.urlopen(url, context=context, timeout=15) as response:
            return response.read().decode()
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise


base = repository_url.rstrip("/")
page = None
for page_url in (f"{base}/{normalized}/", f"{base}/simple/{normalized}/"):
    try:
        page = fetch_project_page(page_url)
    except Exception as error:
        print(f"check_published: cannot query {page_url}: {error}", file=sys.stderr)
        sys.exit(2)
    if page is not None:
        break

if page is None:
    sys.exit(1)  # no project page at all: nothing here can be hosted

hosted = set(re.findall(r">([^<>]+)<", page))
missing = [name for name in artifacts if name not in hosted]
sys.exit(0 if not missing else 1)

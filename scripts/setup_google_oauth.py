"""Do the parts of registering a Google OAuth application that can be automated.

Google publishes no registration endpoint, so Munim cannot ask for a client the
way Cloudflare or Supabase issue one. Somebody has to register an application by
hand. This does everything around that step and then hands over.

    uv run python scripts/setup_google_oauth.py            # for gmail
    uv run python scripts/setup_google_oauth.py --provider stitch
    uv run python scripts/setup_google_oauth.py --project my-existing-project

**It never creates a Google Cloud project.** Project ids are globally unique and
a script that creates one on each run leaves a trail of them behind, so this
uses the project you already have selected. That also means there is no state
file to keep: `.env` holds the answer, and holding the answer is what stops this
running twice.

What it cannot do, and why: `gcloud` has exactly one OAuth command and its own
documentation says "this API cannot be used as a generic management API for all
OAuth clients in your project". It creates Identity-Aware Proxy clients. There
is no API for creating a Desktop-app OAuth client, so that step is the Console,
by hand, for everyone.
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ENV = Path(".env")
API = {"gmail": "gmail.googleapis.com", "stitch": "stitch.googleapis.com"}
REDIRECT = "http://localhost:8976/oauth/callback"


def _run(args: list[str], timeout: float = 90.0) -> tuple[int, str]:
    try:
        done = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return done.returncode, (done.stdout or done.stderr).strip()
    except FileNotFoundError:
        return 127, f"{args[0]} not found"
    except subprocess.TimeoutExpired:
        return 124, f"{' '.join(args[:3])} timed out"


def already_set(provider: str) -> str | None:
    """The client id in .env, if there is one. This is the whole idempotence."""
    key = f"{provider.upper()}_OAUTH_CLIENT_ID"
    if os.environ.get(key):
        return os.environ[key]
    if ENV.exists():
        for line in ENV.read_text().splitlines():
            line = line.strip()
            if line.startswith(f"{key}=") and line.split("=", 1)[1].strip():
                return line.split("=", 1)[1].strip()
    return None


def current_project() -> str | None:
    code, out = _run(["gcloud", "config", "get-value", "project"])
    if code != 0 or not out or out in ("(unset)", "unset"):
        return None
    return out.splitlines()[-1].strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--provider", default="gmail", choices=sorted(API))
    parser.add_argument("--project", help="a Google Cloud project you already "
                                          "have. Defaults to your current one")
    args = parser.parse_args()
    provider = args.provider
    key = provider.upper()

    existing = already_set(provider)
    if existing:
        print(f"{key}_OAUTH_CLIENT_ID is already set ({existing[:28]}...).")
        print("Nothing to do. Delete it from .env first if you want to start over.")
        return 0

    if not shutil.which("gcloud"):
        print("gcloud is not installed, so none of this can be automated.",
              file=sys.stderr)
        print("Install the Google Cloud CLI, or follow the manual steps in the "
              "README under \"Providers that need an application\".",
              file=sys.stderr)
        return 2

    project = args.project or current_project()
    if not project:
        print("No Google Cloud project selected.", file=sys.stderr)
        print("  gcloud projects list          # pick one you already have",
              file=sys.stderr)
        print("  gcloud config set project PROJECT_ID", file=sys.stderr)
        print("\nThis deliberately does not create one: project ids are global "
              "and a script that creates one per run leaves a trail behind.",
              file=sys.stderr)
        return 2

    print(f"Project: {project}")

    api = API[provider]
    code, out = _run(["gcloud", "services", "enable", api, "--project", project],
                     timeout=180.0)
    if code != 0:
        print(f"\nCould not enable {api}: {out}", file=sys.stderr)
        print("You may not have permission on that project, or billing may not "
              "be linked. Enabling it by hand does the same job:", file=sys.stderr)
        print(f"  https://console.cloud.google.com/apis/library/{api}?project={project}",
              file=sys.stderr)
        return 1
    print(f"Enabled {api}. (Already enabled is a no-op, so this is safe to rerun.)")

    # The one step Google does not expose. gcloud's only OAuth command creates
    # Identity-Aware Proxy clients and says so.
    print(f"""
The rest is by hand, because Google publishes no API for it.

  1. https://console.cloud.google.com/auth/clients/create?project={project}
  2. Application type: Desktop app
  3. Name it whatever you like. Create.
  4. Copy the client ID and client secret into .env:

       {key}_OAUTH_CLIENT_ID=...apps.googleusercontent.com
       {key}_OAUTH_CLIENT_SECRET=...

  5. https://console.cloud.google.com/auth/audience?project={project}
     Add your own Google account under Test users.

Step 5 is not optional. {provider} uses Google restricted scopes, so an
unverified application only works for accounts listed there.

If you pick "Web application" instead of "Desktop app", add this redirect:
  {REDIRECT}

Then: munim connect "<client>" {provider}
Check it with: munim doctor
""")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

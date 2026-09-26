#!/usr/bin/env python3
"""Release script for the ha-mashov integration.

Bumps VERSION, manifest.json, reporting.py and CHANGELOG.md, commits and pushes everything
to ``main``, then creates and pushes an annotated ``v<version>`` tag.

Usage: python scripts/release.py <version> [--pre-release]
Run from the repository root (paths are relative to the current directory).
All files are read and written as UTF-8: CHANGELOG.md contains Hebrew, and the
Windows default encoding (cp1252) cannot decode it.
"""

import argparse
from datetime import datetime
import json
import re
import subprocess


def get_current_version():
    """Return the current version string from the VERSION file."""
    with open("VERSION", encoding="utf-8") as f:
        return f.read().strip()


def update_version_file(new_version):
    """Overwrite the VERSION file with ``new_version``."""
    with open("VERSION", "w", encoding="utf-8") as f:
        f.write(new_version)


def update_manifest_version(new_version):
    """Set the ``version`` field in the integration's manifest.json."""
    manifest_path = "custom_components/mashov/manifest.json"
    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)

    manifest["version"] = new_version

    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
        f.write("\n")


def update_reporting_version(new_version):
    """Set ``VERSION`` in reporting.py, which diagnostics and bug reports display."""
    reporting_path = "custom_components/mashov/reporting.py"
    with open(reporting_path, encoding="utf-8") as f:
        content = f.read()

    new_content, count = re.subn(r'^VERSION = "[^"]*"$', f'VERSION = "{new_version}"', content, flags=re.MULTILINE)
    if count != 1:
        raise SystemExit(f"Expected exactly one VERSION line in {reporting_path}, found {count}")

    with open(reporting_path, "w", encoding="utf-8") as f:
        f.write(new_content)


def update_changelog(new_version, is_prerelease=False):
    """Turn the ``[Unreleased]`` section into a dated ``new_version`` entry.

    A fresh, empty ``[Unreleased]`` template is then inserted right after the
    ``# Changelog`` title.
    """
    changelog_path = "CHANGELOG.md"

    # Read current changelog
    with open(changelog_path, encoding="utf-8") as f:
        content = f.read()

    # Get current date
    date_str = datetime.now().strftime("%Y-%m-%d")

    # Create new version entry
    if is_prerelease:
        version_line = f"## [{new_version}] - {date_str} (Pre-release)"
    else:
        version_line = f"## [{new_version}] - {date_str}"

    # Rename the existing [Unreleased] heading to the new version heading
    unreleased_pattern = r"## \[Unreleased\]"
    new_content = re.sub(unreleased_pattern, version_line, content)

    # Add new [Unreleased] section at the top
    unreleased_section = """## [Unreleased]

### Added
- TBD

### Changed
- TBD

### Fixed
- TBD

"""

    # Insert after the title
    title_pattern = r"(# Changelog\n\n)"
    new_content = re.sub(title_pattern, r"\1" + unreleased_section, new_content)

    # Write back
    with open(changelog_path, "w", encoding="utf-8") as f:
        f.write(new_content)


def create_git_tag(version, is_prerelease=False):
    """Create an annotated ``v<version>`` tag, push it and print the ``gh`` release command."""
    tag_name = f"v{version}"

    # Create tag
    subprocess.run(["git", "tag", "-a", tag_name, "-m", f"Release {tag_name}"], check=True)

    # Push tag
    subprocess.run(["git", "push", "origin", tag_name], check=True)

    print(f"✅ Created and pushed tag: {tag_name}")

    if is_prerelease:
        print("🔶 This is a pre-release version")
        print("💡 To create a GitHub release, run:")
        print(
            f"   gh release create {tag_name} --prerelease --title 'Release {tag_name}' --notes 'See CHANGELOG.md for details'"
        )
    else:
        print("💡 To create a GitHub release, run:")
        print(f"   gh release create {tag_name} --title 'Release {tag_name}' --notes 'See CHANGELOG.md for details'")


def main():
    """Parse CLI arguments and run the full release flow."""
    parser = argparse.ArgumentParser(description="Release script for ha-mashov")
    parser.add_argument("version", help="New version (e.g., 0.1.1, 0.2.0-beta.1)")
    parser.add_argument("--pre-release", action="store_true", help="Mark as pre-release")

    args = parser.parse_args()

    current_version = get_current_version()
    new_version = args.version

    print(f"🔄 Updating version from {current_version} to {new_version}")

    # Update files
    update_version_file(new_version)
    update_manifest_version(new_version)
    update_reporting_version(new_version)
    update_changelog(new_version, args.pre_release)

    # Commit and push to main.
    # Stage ALL changes so manual edits (icons, examples, etc.) are included
    subprocess.run(["git", "add", "-A"], check=True)
    subprocess.run(["git", "commit", "-m", f"Bump version to {new_version}"], check=True)
    subprocess.run(["git", "push", "origin", "main"], check=True)

    # Create tag
    create_git_tag(new_version, args.pre_release)

    print(f"🎉 Successfully released version {new_version}")


if __name__ == "__main__":
    main()

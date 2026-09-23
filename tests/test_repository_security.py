# Copyright (c) 2026 Hawarisma Rafanidya Singgih
# SPDX-License-Identifier: MIT

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SECRET_SIGNATURES = {
    "AWS access key": re.compile(r"AKIA[0-9A-Z]{16}"),
    "GitHub token": re.compile(r"(?:github_pat_[A-Za-z0-9_]{20,}|gh[pousr]_[A-Za-z0-9]{30,})"),
    "API token format": re.compile(r"sk-(?:proj-)?[A-Za-z0-9_-]{20,}"),
    "Google API key": re.compile(r"AIza[0-9A-Za-z_-]{35}"),
    "Slack token": re.compile(r"xox[baprs]-[A-Za-z0-9-]{20,}"),
    "private key": re.compile(r"-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----"),
}


def repository_text_files() -> list[Path]:
    text_suffixes = {".css", ".csv", ".md", ".py", ".toml", ".txt"}
    text_names = {"CODEOWNERS", "LICENSE"}
    files = [
        ROOT / ".gitignore",
        ROOT / ".streamlit" / "config.toml",
        ROOT / "ATTRIBUTION.md",
        ROOT / "LICENSE",
        ROOT / "README.md",
        ROOT / "SECURITY.md",
        ROOT / "app.py",
        ROOT / "requirements.txt",
    ]
    for directory in (".github", "pages", "src", "tests"):
        files.extend(
            path
            for path in (ROOT / directory).rglob("*")
            if path.is_file() and (path.suffix in text_suffixes or path.name in text_names)
        )
    files.extend((ROOT / "assets").glob("*.css"))
    files.extend((ROOT / "sample_data").glob("*.csv"))
    return sorted(set(files))


class RepositorySecurityTests(unittest.TestCase):
    def test_repository_text_has_no_recognized_secret_signature(self):
        findings: list[str] = []
        for path in repository_text_files():
            text = path.read_text(encoding="utf-8")
            for label, signature in SECRET_SIGNATURES.items():
                if signature.search(text):
                    findings.append(f"{path.relative_to(ROOT)}: {label}")
        self.assertEqual(findings, [], f"Potential credentials found: {findings}")

    def test_gitignore_covers_local_credentials_and_user_data(self):
        ignored = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        required = {
            ".env",
            ".env.*",
            "secrets.toml",
            ".streamlit/secrets.toml",
            "data/**",
            "!data/.gitkeep",
            "cookies*.json",
            "storage_state*.json",
            "auth_state*.json",
            "*.pem",
            "*.key",
            "*.p12",
            "*.pfx",
        }
        self.assertEqual(sorted(required - set(ignored)), [])


if __name__ == "__main__":
    unittest.main()

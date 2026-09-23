# Security and Privacy

MIDETA is designed to run locally and keep authentication data out of the repository and exported datasets.

## Credential handling

- MIDETA never asks for, reads, or stores account passwords.
- Login is performed directly on the official platform or publisher website in a dedicated Chrome profile.
- Browser cookies and sessions remain under `data/browser_profiles/`, which is ignored by Git.
- Optional API tokens remain under `data/private/` or environment variables, both of which are ignored by Git.
- Passwords, cookies, sessions, and API tokens are not written to CSV/XLSX exports or analysis history.
- Do not hard-code credentials in Python, configuration, test, sample-data, or documentation files.

## Before pushing to GitHub

1. Run the automated test suite.
2. Review `git status --short` and confirm that only intended source and documentation files are listed.
3. Confirm that no `.env`, `secrets.toml`, browser profile, database, spreadsheet export, cookie file, or private key is staged.
4. If a real secret was ever committed, revoke or rotate it immediately. Removing it from the latest file does not remove it from Git history.

## Reporting a vulnerability

Do not publish passwords, tokens, cookies, private URLs, or personal datasets in a public issue. Contact the repository owner privately and include only the minimum reproduction details needed.

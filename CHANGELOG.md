# Changelog

## [1.1.0] - 2026-03-21

### Fixed
- Wait for OAuth redirect to complete before extracting authorization code
- Use flexible regex for code extraction (fixes crash on changed code format)
- Safer token response handling with `.get()`

### Changed
- README rewritten with corrected Quick Start (`python -m pip`, `ensurepip`, `python` vs `py`)
- Removed unused `webdriver-manager` dependency
- Script renamed from `GetToken` to `get_token.py`
- Quick Start now clones this repo instead of downloading from an external gist

### Added
- `requirements.txt`
- Troubleshooting section in README
- `CHANGELOG.md`

## [1.0.0] - 2026-03-21

### Added
- Initial Selenium-based token fetching script (based on fuatakgun's gist)
- Basic README

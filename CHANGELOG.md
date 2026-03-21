# Changelog

## [1.2.0] - 2026-03-21

### Fixed
- Quick Start now works on repeated runs (clone-or-pull, recreate venv each time)
- Ctrl+C now properly closes Chrome instead of leaving orphaned processes
- Minimum Selenium version bumped to 4.6.0 (required for automatic ChromeDriver management)

### Changed
- Quick Start uses `$env:TEMP\KiaHyundaiToken` as fixed location
- `deactivate` called before recreating venv to avoid Permission Denied errors
- Removed outdated comments about manual chromedriver installation

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

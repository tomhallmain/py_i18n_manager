# i18n Translation Manager

A PyQt6-based desktop application for managing internationalization (i18n) translations in software projects. This tool helps developers and translators efficiently manage translation files, track missing translations, and maintain translation quality.

## Features

- **Project Management**
  - Select and manage multiple translation projects
  - Recent projects tracking
  - Automatic project state persistence

- **Translation Statistics**
  - Total translations count
  - Total locales count
  - Missing translations tracking
  - Invalid Unicode detection
  - Invalid indices detection
  - Stale translations identification

- **Translation Management**
  - View and edit translations in a user-friendly interface
  - Update PO files with new translations
  - Create MO files for deployment
  - Track modified locales for efficient updates

- **Quality Control**
  - Real-time validation of translations
  - Detection of invalid Unicode characters
  - Detection of invalid format string indices
  - Detection of invalid brace formatting
  - Detection of invalid leading spaces
  - Detection of invalid newlines
  - Tracking of stale translations

- **User Interface**
  - Clean, modern interface with PyQt6
  - Tabbed interface for different views
  - Outstanding items window for quick fixes
  - All translations view for comprehensive editing

## Installation

1. Clone the repository

2. Create a virtual environment (recommended):
```bash
python -m venv venv
venv/bin/activate  # On Unix: source venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

## Usage

1. Launch the application:
```bash
python app.py
```

2. Select a project directory containing a locale directory and translation files (PO files)

3. Use the interface to:
   - Check translation status
   - Update PO files
   - Create MO files
   - View and edit translations
   - Track translation statistics

## Requirements

- Python 3.8 or higher
- PyQt6
- polib (for PO file handling)

## Encoding Support

The application currently supports UTF-8 encoding only, which is essential for proper handling of CJK (Chinese, Japanese, Korean) and other non-Latin character sets. All translation files (PO and MO) are read and written using UTF-8 encoding to ensure compatibility with these languages.

This means that if your project contains PO files with escaped unicode (i.e., \uXXXX format) then they will all appear as invalid unicode at first, until you have saved the PO files once with this application. You should not need to manually fix these, as attempts will be made to fix them automatically. As always, be sure to also update the MO files after saving the PO files, as your encoding will need to be updated for both.

## Directory Structure Support

The application supports both common directory structures for i18n projects:
- `locale/` - The traditional gettext directory structure
- `locales/` - An alternative structure used by some projects

The application will automatically detect which directory structure is being used in your project and adapt accordingly. If both directories exist, it will default to using the `locale/` directory.

# Limitations

The PyQt6 library may not be well-supported on all OS, I use Windows for this project and have not experienced any issues but on OS X it may fail to load. At some point I plan to enable a version for OS X.


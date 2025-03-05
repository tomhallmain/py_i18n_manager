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
  - Tracking of stale translations

- **User Interface**
  - Clean, modern interface with PyQt6
  - Tabbed interface for different views
  - Outstanding items window for quick fixes
  - All translations view for comprehensive editing

## Installation

1. Clone the repository:
```bash
git clone https://github.com/tomhallmain/py_i18n_manager.git
cd i18n
```

2. Create a virtual environment (recommended):
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
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

2. Select a project directory containing translation files (PO files)

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


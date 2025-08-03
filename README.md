# i18n Translation Manager

A PyQt6-based desktop application for managing internationalization (i18n) translations in software projects. This tool helps developers and translators efficiently manage translation files, track missing translations, and maintain translation quality.

## Features

- **Project Management**: Select and manage multiple translation projects with automatic state persistence
- **Translation Statistics**: Track total translations, locales, missing translations, and various validation metrics
- **Translation Management**: View/edit translations, update PO files, create MO files
- **Quality Control**: Real-time validation of translations including Unicode, format strings, braces, spaces, and newlines
- **Babel Support**: Automatic detection and use of `babel.cfg` files for enhanced POT generation across multiple file formats
- **Bulk Project Analysis**: Quickly determine which projects need translation updates
- **Cross Project Analysis**: Allows quick sharing of translations between projects
- **User Interface**: Clean, modern PyQt6 interface with tabbed views and dedicated translation windows

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
3. Use the interface to check status, update files, and manage translations

## Requirements

- Python 3.8 or higher
- PyQt6
- polib
- babel

## Encoding Support

The application currently supports UTF-8 encoding only, which is essential for proper handling of CJK (Chinese, Japanese, Korean) and other non-Latin character sets. All translation files (PO and MO) are read and written using UTF-8 encoding to ensure compatibility with these languages.

This means that if your project contains PO files with escaped unicode (i.e., \uXXXX format) then they will all appear as invalid unicode at first, until you have saved the PO files once with this application. You should not need to manually fix these, as attempts will be made to fix them automatically. As always, be sure to also update the MO files after saving the PO files, as your encoding will need to be updated for both.

## Directory Structure Support

The application supports both common directory structures for i18n projects:
- `locale/` - The traditional gettext directory structure
- `locales/` - An alternative structure used by some projects

The application will automatically detect which directory structure is being used in your project and adapt accordingly. If both directories exist, it will default to using the `locale/` directory.

## Babel Configuration Support

The application automatically detects and uses `babel.cfg` files for enhanced POT generation. When a `babel.cfg` file is found in your project root, the application will use Babel's configuration to extract translatable strings from multiple file formats beyond just Python files.

### How it works:
1. **Automatic Detection**: The application automatically looks for a `babel.cfg` file in your project root directory
2. **Enhanced Extraction**: When found, Babel's configuration is used to extract strings from all file types specified in the config
3. **Fallback**: If no `babel.cfg` file is found, the application falls back to the default Python-only extraction method
4. **Configuration**: You can also manually specify a custom path to a `babel.cfg` file through project settings

### Example babel.cfg file:
```ini
[extractors]
*.py = python
*.js = javascript
*.html = html
*.xml = xml
*.json = json

[javascript:extract_from_file]
*.js = i18n.tr
*.js = gettext

[html:extract_from_file]
*.html = i18n.tr
*.html = gettext
```

This allows you to extract translatable strings from JavaScript, HTML, XML, JSON, and other file formats in addition to Python files.

A complete example `babel.cfg` file is provided as `babel.cfg.example` in the project root.

You can test the Babel integration by running:
```bash
python test_babel_integration.py
```

# Limitations

The PyQt6 library may not be well-supported on all OS, I use Windows for this project and have not experienced any issues but on OS X it may fail to load. At some point I plan to enable a version for OS X.


# Ruby I18N Manager Documentation

## Overview

The `RubyI18NManager` class manages internationalization (i18n) for Ruby on Rails projects using YAML translation files. Unlike Python projects that use Gettext (POT/PO/MO files), Ruby/Rails projects use YAML files organized in `config/locales/` with nested key structures.

## Architecture

### Inheritance

`RubyI18NManager` extends `I18NManagerBase`, which provides the common interface for all i18n managers. This allows the application to work with both Python (Gettext) and Ruby (YAML) projects through a unified interface.

### Key Design Decisions

1. **Dual YAML Library Strategy**: Uses both `PyYAML` (for reading) and `ruamel.yaml` (for writing)
   - **PyYAML**: Fast, simple, good for reading. Cannot preserve formatting (quotes, comments)
   - **ruamel.yaml**: Slower but preserves formatting, comments, and structure. Essential for maintaining Rails conventions

2. **File Structure Support**: Handles two Rails i18n patterns:
   - **Directory structure**: `config/locales/en/application.yml`
   - **Flat files**: `config/locales/en.yml`, `config/locales/devise.en.yml`

3. **Source File Tracking**: Maintains `_source_files` dictionary to map translation keys back to their original files, enabling in-place updates

## Data Structures

### Instance Variables

```python
self._source_files: dict[str, dict[str, str]]
# Maps translation keys to their source files: {key: {locale: file_path}}
# Example: {"tasks.form.title": {"en": "config/locales/en/views/tasks/_form.yml"}}

self._default_locale_files: set[str]
# Tracks all YAML files that exist for the default locale
# Used to replicate file structure for new locales

self._original_file_content: dict[str, str]
# Stores original file content (with comments) for each file
# Key: file path, Value: raw file content as string
# Used for comment preservation when writing
```

### Translation Key Format

Translation keys use dot notation to represent nested YAML structure:
- YAML: `en: tasks: form: title: "Task Details"`
- Key: `"tasks.form.title"`

## Main Workflow

### 1. Initialization (`__init__`)

1. Calls parent `I18NManagerBase.__init__()`
2. Initializes tracking dictionaries (`_source_files`, `_default_locale_files`, `_original_file_content`)
3. Detects locale directory structure (`_detect_locale_directory()`)

### 2. Gathering Files (`gather_yaml_files()`)

Scans `config/locales/` for YAML files and organizes them by locale:

**Directory Structure Detection:**
- Looks for subdirectories like `en/`, `es/`, `de/`
- Recursively finds all `.yml` files in each locale directory

**Flat File Detection:**
- Scans for files directly in `config/locales/` like `en.yml`, `devise.en.yml`
- Extracts locale from filename using regex pattern: `^[a-z]{2}([-_][A-Z]{2})?$`
- Handles patterns:
  - `en.yml` → locale: `en`
  - `devise.en.yml` → locale: `en`
  - `en-GB.yml` → locale: `en-GB`

**Returns:** `dict[str, list[str]]` mapping locale codes to file paths

### 3. Parsing YAML Files (`_parse_yaml_files()`)

Two-pass parsing:

**Pass 1: Default Locale (Base Translations)**
- Parses all files for the default locale (typically `en`)
- Extracts nested keys using `_extract_translation_keys()`
- Creates `TranslationGroup` objects marked as `is_in_base=True`
- Tracks source file for each key in `_source_files`
- Stores original file content (with comments) in `_original_file_content`
- Adds files to `_default_locale_files` set

**Pass 2: Other Locales**
- Parses files for all other locales
- Only processes keys that exist in the base (from Pass 1)
- Tracks source files for each locale
- Adds translations to existing `TranslationGroup` objects

**Key Extraction:**
- Recursively walks nested YAML dictionaries
- Builds dot-notation keys: `"tasks.form.title"`
- Handles nested structures of arbitrary depth

### 4. Writing YAML Files (`write_locale_yaml_files()`)

Complex multi-step process for writing translations back to files:

#### Step 1: Organize Translations by File

For each translation key:
1. Get translation value (or empty string `""` if missing)
2. Determine target file path:
   - **If source file exists for this locale**: Use it
   - **Else if source file exists for default locale**: Convert path (e.g., `devise.en.yml` → `devise.de.yml`)
   - **Else**: Use heuristics (`_determine_yaml_file_path()`)

#### Step 2: Load Existing File Content

For each target file:
- If file exists: Load YAML data and original content (for comments)
- Else if default locale file exists: Use it as template (for comments)
- Preserve all existing keys (not just ones being updated)

#### Step 3: Create Missing Files for Non-Default Locales

For non-default locales, ensure all files from default locale are created:
- Convert default locale file paths to target locale paths
- Handle three patterns:
  - Directory: `en/application.yml` → `de/application.yml`
  - Flat: `en.yml` → `de.yml`
  - Named flat: `devise.en.yml` → `devise.de.yml`
- Populate with translations that belong to each file
- Use empty strings `""` for missing translations

#### Step 4: Write Files

For each file:
- Build YAML structure with locale as top-level key
- Use `_custom_yaml_dump()` which:
  - Prefers `ruamel.yaml` (preserves comments and quotes)
  - Falls back to `PyYAML` if `ruamel.yaml` fails
- Ensure string values are quoted (Rails convention)

## File Path Determination

### Source File Priority

When writing a translation, the file path is determined in this order:

1. **Existing source file for target locale**: `_source_files[key][locale]`
2. **Default locale source file converted**: Convert `_source_files[key][default_locale]` path
3. **Heuristics**: Use `_determine_yaml_file_path()` based on key structure

### Path Conversion Logic

The code handles three file naming patterns:

```python
# Pattern 1: Directory structure
en/application.yml → de/application.yml

# Pattern 2: Simple flat file
en.yml → de.yml

# Pattern 3: Named flat file
devise.en.yml → devise.de.yml
```

### Heuristic File Path Determination

When no source file exists, `_determine_yaml_file_path()` uses key structure:

- `"views.tasks.form.title"` → `views/tasks/_form.yml`
- `"models.task.title"` → `models/task.yml`
- `"tasks.form.title"` → `tasks/_form.yml` (if namespace is known)
- Single-part keys → `application.yml`

**Note**: This is a fallback. The preferred method is tracking source files.

## YAML Writing and Formatting

### Comment Preservation

Comments are preserved according to this priority:

1. **Current Locale File Exists**: Preserve comments from that file
2. **Default Locale Template**: If target file doesn't exist, inherit comments from default locale file
3. **New Files**: No comments (new files start clean)

**Implementation:**
- `_original_file_content` stores raw file content (with comments)
- `ruamel.yaml` loads this content and preserves comments during merge
- Comments are associated with specific keys/values in the YAML structure

### String Quoting

Rails convention requires quoted string values to prevent YAML from interpreting special strings as booleans/null.

**Strategy:**
- All string values are wrapped in `DoubleQuotedScalarString` (from `ruamel.yaml`)
- Keys are NOT quoted (only values)
- Empty strings are quoted: `""`

**Methods:**
- `_quote_string_values()`: Converts plain dicts (loses comments)
- `_quote_string_values_in_place()`: Modifies `ruamel.yaml` structures in place (preserves comments)

### YAML Dumper Selection

`_custom_yaml_dump()` chooses the appropriate dumper:

1. **ruamel.yaml** (preferred):
   - Preserves comments and quotes
   - Handles duplicate keys (silently uses last value)
   - Replaces locale key when using default locale file as template

2. **PyYAML** (fallback):
   - Used if `ruamel.yaml` fails or is unavailable
   - Custom dumper quotes values but not keys
   - Post-processing regex removes quotes from keys
   - Does NOT preserve comments

## Key Methods Reference

### File Operations

- `gather_yaml_files()`: Scan and organize YAML files by locale
- `_parse_yaml_files()`: Parse YAML files and extract translations
- `write_locale_yaml_files()`: Write translations back to YAML files

### Path and Structure

- `_detect_locale_directory()`: Detect `config/locales` vs `locale` vs `locales`
- `_determine_yaml_file_path()`: Heuristic file path from translation key
- `_add_to_nested_dict()`: Add translation to nested dictionary structure

### YAML Processing

- `_extract_translation_keys()`: Recursively extract keys from nested YAML
- `_get_nested_value()`: Get value from nested dict using dot-notation key
- `_custom_yaml_dump()`: Smart YAML dumper (ruamel.yaml or PyYAML)
- `_ruamel_yaml_dump()`: ruamel.yaml dumper with comment preservation
- `_pyyaml_dump()`: PyYAML fallback dumper

### String Quoting

- `_quote_string_values()`: Quote strings in plain dicts
- `_quote_string_values_in_place()`: Quote strings in ruamel.yaml structures
- `_merge_ruamel_data()`: Merge data while preserving ruamel.yaml structure

## Gotchas and Edge Cases

### 1. Duplicate Keys in YAML Files

**Issue**: YAML files may contain duplicate keys (invalid YAML, but Rails tolerates it)

**Handling**: 
- `ruamel.yaml` is configured with `allow_duplicate_keys = True`
- Last value wins, duplicates are silently removed
- Warning logged if duplicates are detected during loading

**Example**:
```yaml
en:
  views:
    tasks:
      index:
        select_project: "Select a project:"
        # ... later in same file ...
        select_project: "Select a project:"  # Duplicate!
```

### 2. Missing Translations

**Behavior**: Missing translations are written as empty quoted strings `""`

**Rationale**: 
- Ensures all keys are present in all locale files
- Makes it clear which translations need work
- Prevents missing key errors in Rails

**Logging**: Counts empty values written (not "skipped")

### 3. File Path Conversion Edge Cases

**Issue**: Converting default locale file paths to target locale paths can fail

**Fallback**: Uses heuristic file path determination if conversion fails

**Common Issues**:
- Files with unusual naming patterns
- Locale codes in unexpected positions
- Mixed directory/flat file structures

### 4. Comment Loss During Merging

**Issue**: Converting `ruamel.yaml` structures to plain dicts loses comments

**Solution**: Use `_quote_string_values_in_place()` which modifies structures in place

**When It Happens**:
- When using `_quote_string_values()` instead of `_quote_string_values_in_place()`
- When converting `CommentedMap`/`CommentedSeq` to plain dict/list

### 5. Locale Key Replacement

**Issue**: When using default locale file as template for new locale, top-level key must change

**Example**: `en.yml` template used for `de.yml` must have `de:` not `en:`

**Solution**: `_ruamel_yaml_dump()` detects this and replaces the locale key in the structure

### 6. Flat Files with Multiple Locales

**Issue**: Flat files like `en.yml` may contain multiple locales (rare but possible)

**Handling**: 
- When updating, preserves entire file structure
- Only updates the specific locale being written
- Other locales remain unchanged

### 7. Empty Files for New Locales

**Issue**: New locales may have no translations yet, but files should still be created

**Solution**: Second loop in `write_locale_yaml_files()` creates all default locale files for new locales, populated with empty strings

### 8. Source File Tracking Gaps

**Issue**: If a translation key has no tracked source file, heuristics must be used

**Limitation**: Heuristics may not match actual file structure

**Best Practice**: Always track source files during parsing (done automatically)

## Common Issues and Troubleshooting

### Problem: Translations Not Written

**Check**:
1. Are translations marked as `is_in_base=True`? (only base translations are written)
2. Is the locale in the project settings?
3. Are there errors in the log?

### Problem: Comments Lost

**Check**:
1. Is `ruamel.yaml` installed? (`RUAMEL_AVAILABLE`)
2. Did the file exist before? (comments only preserved from existing files)
3. Are you using `_quote_string_values_in_place()` not `_quote_string_values()`?

### Problem: Wrong File Paths Created

**Check**:
1. Are source files being tracked? (`_source_files` dictionary)
2. Is path conversion logic working? (check logs for conversion attempts)
3. Are heuristics being used? (fallback, may not match structure)

### Problem: Values Not Quoted

**Check**:
1. Is `ruamel.yaml` available? (falls back to PyYAML which may not quote)
2. Are values being wrapped in `DoubleQuotedScalarString`?
3. Check `_quote_string_values()` or `_quote_string_values_in_place()` calls

### Problem: Duplicate Keys Warning

**Check**:
1. Does the source YAML file have duplicate keys? (invalid but tolerated)
2. Check the file mentioned in the warning
3. ruamel.yaml will use the last value, removing duplicates

### Problem: Empty Files Created

**Expected Behavior**: Empty files are created for new locales with empty string values

**If Unwanted**: This is by design to ensure all keys are present. Empty strings indicate missing translations.

## Performance Considerations

1. **ruamel.yaml is slower** than PyYAML but necessary for comment preservation
2. **File I/O**: Multiple file reads/writes per locale (could be optimized)
3. **Deep copying**: Used to preserve existing file structure (memory intensive for large files)
4. **Recursive operations**: Key extraction and value setting use recursion (stack depth for very deep structures)

## Future Improvements

1. **Caching**: Cache parsed YAML data to avoid re-parsing
2. **Batch Operations**: Write multiple locales in single pass
3. **Incremental Updates**: Only update changed keys
4. **Better Heuristics**: Improve file path determination when source files unknown
5. **Validation**: Validate YAML structure before writing
6. **Error Recovery**: Better handling of malformed YAML files

## Testing Recommendations

When testing the Ruby i18n manager, consider:

1. **File Structure Variations**: Test both directory and flat file structures
2. **Comment Preservation**: Verify comments are preserved in various scenarios
3. **Empty Translations**: Ensure empty strings are written correctly
4. **Path Conversion**: Test all three path conversion patterns
5. **Duplicate Keys**: Test handling of duplicate keys in source files
6. **New Locales**: Test creating files for locales that don't exist yet
7. **Mixed Structures**: Test projects with both directory and flat files
8. **Special Characters**: Test Unicode, quotes, and special YAML characters
9. **Large Files**: Test performance with many translations
10. **Error Cases**: Test malformed YAML, missing files, permission errors

## Related Files

- `i18n/i18n_manager_base.py`: Base class defining common interface
- `i18n/python/python_i18n_manager.py`: Python/Gettext implementation (for comparison)
- `i18n/translation_group.py`: TranslationGroup data structure
- `i18n/translation_manager_results.py`: Results container for operations

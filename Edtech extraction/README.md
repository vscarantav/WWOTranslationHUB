# EdTech HTML Extraction

This standalone utility logs in to EdTech, walks every chapter page listed in a
book's table of contents, and saves the source content as HTML. It does not call
an AI service, translate content, modify fields, apply HTML, save changes, or
repopulate a book.

## Setup

Python 3.10 or newer is recommended.

```powershell
py -m pip install -r requirements.txt
py -m playwright install chromium
```

## Run

Double-click `run_extraction.bat` and paste the book URL when prompted, or run:

```powershell
py extractor.py https://books.byui.edu/your_book_name
```

If an editor URL such as `https://books.byui.edu/editor/your_book_name` is
entered, the extractor automatically converts it to the public book root where
the table of contents is available.

A visible Chromium window opens. Complete the normal Google SSO login if
prompted. The script then processes the whole table of contents. For each page,
the console reports when it clicks the visible **Edit chapter** link, confirms
the `/editor/...` page opened, clicks the **HTML** view button, and reads the
CodeMirror container labeled `Document HTML source`. Because CodeMirror renders
only part of long documents in the DOM, the extractor focuses the container,
uses **Select All** and **Copy**, and reads the complete HTML from Chromium's
clipboard. These controls expose the source; the script never applies or saves
anything in EdTech.

Chapter titles are captured from the table of contents before opening the new
editor. The extractor does not depend on the retired `#chapter-title` editor
element.

By default, results are written to:

- `output/raw_html/001_unidade_1.html`,
  `002_licao_1_preparar_se_para_o_sucesso.html`, and so on
- `output/edtech_mapping.json`, which records each page's title, URL, filename,
  local path, and absolute path
- `output/link_mapping.json`, which maps both full EdTech URLs and URL paths to
  their correctly named local HTML files

To choose another location:

```powershell
py extractor.py https://books.byui.edu/your_book_name --output-dir C:\path\to\output
```

Filenames have a zero-padded TOC position followed by the real page title. This
keeps unit dividers distinct from numbered lessons and preserves book order.
An earlier run's extractor-owned HTML files and mappings are replaced. No other
files in the output directory are removed. If any chapter fails, the extractor
still visits the remaining chapters and exits with an error summary;
successfully extracted pages remain available.

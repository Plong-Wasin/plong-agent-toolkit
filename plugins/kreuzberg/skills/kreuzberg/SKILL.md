---
name: kreuzberg
description: >
  How to extract text from binary document formats (DOCX, PDF, PPTX, XLSX, ODT, etc.) using
  kreuzberg via Docker. Use this skill whenever the user needs to read a binary document that
  the available file-reading tools cannot open directly. Trigger for any request to extract, read, or parse
  content from DOCX, PDF, PPTX, XLSX, or similar binary formats. Do NOT use for plain text
  files (.md, .txt, .csv, .json) which the agent can read directly without Docker.
---

# Kreuzberg via Docker

Kreuzberg is a high-performance document text extraction tool. Run it via Docker — no local install needed.

## Docker Image

```
goldziher/kreuzberg:latest
```

## Step 1: Detect the Environment

Before constructing the command, determine which shell/OS the user is running:

- **Windows + Git Bash**: Requires `MSYS_NO_PATHCONV=1` prefix to prevent Git Bash from mangling `/data/...` paths into `C:/Program Files/Git/data/...`
- **Windows + PowerShell / CMD**: No prefix needed; use Windows-style volume paths
- **Linux / macOS / WSL**: No prefix needed; use Unix-style paths

If unsure, ask the user which shell they are using.

## Step 2: Construct the Command

Mount the **folder** containing the file (not the file itself), then reference the file inside the container as `/data/<filename>`.

### Windows — Git Bash

```bash
MSYS_NO_PATHCONV=1 docker run --rm \
  -v "/c/path/to/folder:/data" \
  goldziher/kreuzberg extract "/data/<filename>"
```

### Windows — PowerShell

```powershell
docker run --rm `
  -v "C:\path\to\folder:/data" `
  goldziher/kreuzberg extract "/data/<filename>"
```

### Linux / macOS / WSL

```bash
docker run --rm \
  -v "/path/to/folder:/data" \
  goldziher/kreuzberg extract "/data/<filename>"
```

Ask the user for the full file path if not provided, then derive the folder and filename from it.

## Path Mounting Rules

- Mount the **folder** containing the file, not the file itself
- Quote the extract path when the filename contains spaces: `"/data/my file.docx"`
- Unicode filenames (Thai, CJK, etc.) work without special handling

## Examples

Given file path `/home/user/work/report.pdf` on Linux:
```bash
docker run --rm \
  -v "/home/user/work:/data" \
  goldziher/kreuzberg extract "/data/report.pdf"
```

Given file path `C:\work\my document.docx` on Windows Git Bash:
```bash
MSYS_NO_PATHCONV=1 docker run --rm \
  -v "/c/work:/data" \
  goldziher/kreuzberg extract "/data/my document.docx"
```

## Supported Formats

DOCX, PDF, PPTX, XLSX, ODT, and other common document formats.

## Notes

- First run pulls the image (~few hundred MB); subsequent runs are fast
- Output is plain text to stdout — pipe or redirect as needed
- Thai text and Unicode filenames work without special handling
- If the user is on WSL, treat it as Linux — no `MSYS_NO_PATHCONV=1` needed

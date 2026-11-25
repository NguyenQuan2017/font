# Font Catalog Pack

Workspace for generating the 72-font catalog pack using the original import contract.

## Output
GitHub Actions builds `dist/Font_Catalog_Pack.zip` from Google Fonts source files. The archive contains one root folder, `README.md`, `fonts.json`, and actual font-rendered previews.

## Build
Run **Actions → Build Font Catalog Pack → Run workflow**. The workflow downloads font source files and metadata from the official Google Fonts repository, verifies family/license metadata, renders real previews using the downloaded font files, validates the manifest and archive limits, then uploads the ZIP as a workflow artifact.

## Important
This repository contains the build pipeline, not a claim that the ZIP has already been generated. The ZIP is considered ready only after the workflow succeeds and its validation summary reports all 72 fonts and preview images.

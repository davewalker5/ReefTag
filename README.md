[![GitHub issues](https://img.shields.io/github/issues/davewalker5/ReefTag)](https://github.com/davewalker5/ReefTag/issues)
[![Releases](https://img.shields.io/github/v/release/davewalker5/ReefTag.svg?include_prereleases)](https://github.com/davewalker5/ReefTag/releases)
[![License](https://img.shields.io/badge/License-mit-blue.svg)](https://github.com/davewalker5/ReefTag/blob/main/LICENSE)
[![Language](https://img.shields.io/badge/language-python-blue.svg)](https://www.python.org)
[![Language](https://img.shields.io/badge/database-SQLite-blue.svg)](https://github.com/davewalker5/ReefTag/)
[![GitHub code size in bytes](https://img.shields.io/github/languages/code-size/davewalker5/ReefTag)](https://github.com/davewalker5/ReefTag/)

## Overview

<img src="https://github.com/davewalker5/ReefTag/blob/main/diagrams/main-window.png" alt="ReefTag Main Window" width="100%">

**ReefTag** is a Python desktop application for identifying, annotating and cataloguing marine wildlife in underwater photographs.

Developed following a visit to the Maldives in October 2026, it is the latest in a series of small software projects inspired by the underwater photographs and video footage collected during the trip:

- _ReefFrame_ enhances and processes underwater footage
- _FishTrack_ explores the detection and tracking of fish within video sequences
- _ReefTag_ provides a simple, interactive workspace for examining still images, identifying individual fish and building a reusable catalogue of the species encountered

It is manually operated, rather than an automated classifier, with the user making the identification and _ReefTag_ handling the annotation, organisation and persistence of the resulting data.

### Features

- **Browse and examine photographs** — navigate PNG and JPEG images, adjust brightness, zoom up to 400% and pan using scrollbars or drag controls without changing the originals
- **Identify and annotate fish** — mark individual fish at their original image positions, including multiple individuals of the same species
- **Return to unknown fish** — mark unidentified individuals with question marks and flag images for further examination
- **Maintain a species catalogue** — reuse common and scientific names, edit species details and organise species into categories
- **Find previous observations** — filter images by an identified species and revisit or revise saved annotations
- **Record footage dates** — use folder defaults or set dates for individual images
- **Preserve and recover work** — save observations in SQLite, restore your working session and reconnect image paths after folders move
- **Import and export observations** — exchange identifications and unknown markers as CSV using the File menu, with duplicate detection on import
- **Transfer to Nature Recorder** — transfer categorised species and dated sightings for subsequent analysis and reporting

### How It Works

The workflow is as follows:

1. Select a folder containing underwater photographs and set its footage date
2. Choose an image and examine it, adjusting brightness or zoom as necessary
3. Click on a fish and select an existing species or enter its common and scientific names, optionally assigning a category
4. If you cannot identify a fish yet, mark it as unknown and return to it later
5. Repeat for other fish, then move on to the next photograph

Identified fish appear as numbered markers, while unidentified fish appear as question marks. The underlying photograph remains unchanged, and marker coordinates are retained relative to the original image.

Observations are stored in a local SQLite database, allowing previously catalogued images and species to be revisited in subsequent sessions.

When ready, identified species and sightings can be transferred to _Nature Recorder_ using a separate command-line tool.

### CSV Import and Export

Use **File → Export** to save identifications and unknown markers for the current folder.
The export includes saved records for that folder, even if their images are currently missing
from disk; subfolders and species filters do not change its scope. Further Examination is
written as `0` or `1`, and image names contain their full stored paths.

Use **File → Import** to load a previously exported CSV, with or without a folder open.
Exact marker duplicates are skipped, including duplicates within the file. Existing image
dates and species catalogue details are retained; new species and categories are created
as needed. Imported examination flags are merged, and unknown markers always flag their image.
Image paths need not exist on this computer: **Tools → Check Image Paths** can reconnect them.

Imports preserve identification numbers. If a number already belongs to a different position
in the same image, species names conflict with the catalogue, or a row is invalid, the entire
import is cancelled without saving changes. The error identifies the CSV line where possible.
Completion dialogs show image, identification, unknown marker and duplicate counts.

### Design Philosophy

_ReefTag_ is intended to be a small, practical field-cataloguing tool, rather than a comprehensive marine biology or image-analysis platform.

It does not attempt to recognise species automatically, validate taxonomic names against external databases or replace specialist identification resources. Instead, it supports the process of examining photographs, making identifications and maintaining an organised record of what has been observed.

## Getting Started

Please see the [Wiki](https://github.com/davewalker5/ReefTag/wiki) for the user guide, controls and further details.

## Authors

- **Dave Walker** - _Initial work_

## Feedback

To report an issue or suggest an improvement, please use the project's [GitHub Issues](https://github.com/davewalker5/ReefTag/issues) page.

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.

[![GitHub issues](https://img.shields.io/github/issues/davewalker5/ReefTag)](https://github.com/davewalker5/ReefTag/issues)
[![Releases](https://img.shields.io/github/v/release/davewalker5/ReefTag.svg?include_prereleases)](https://github.com/davewalker5/ReefTag/releases)
[![License](https://img.shields.io/badge/License-mit-blue.svg)](https://github.com/davewalker5/ReefTag/blob/main/LICENSE)
[![Language](https://img.shields.io/badge/language-python-blue.svg)](https://www.python.org)
[![Language](https://img.shields.io/badge/database-SQLite-blue.svg)](https://github.com/davewalker5/ReefTag/)
[![GitHub code size in bytes](https://img.shields.io/github/languages/code-size/davewalker5/ReefTag)](https://github.com/davewalker5/ReefTag/)

## Overview

<img src="https://github.com/davewalker5/ReefTag/blob/main/diagrams/main-window.png" alt="ReefTag Main Window" width="100%">

_ReefTag_ is a Python desktop application for identifying, annotating and cataloguing marine wildlife in underwater photographs.

Developed following a visit to the Maldives in October 2026, it is the latest in a series of small software projects inspired by the underwater photographs and video footage collected during the trip:

- _ReefFrame_ enhances and processes underwater footage
- _FishTrack_ explores the detection and tracking of fish within video sequences
- _ReefTag_ provides a simple, interactive workspace for examining still images, identifying individual fish and building a catalogue of the species encountered

_ReefTag_ is intended to be a small, practical cataloguing tool, supporting the process of examining representative frames from video footage, making manual identifications and maintaining an organised record of what has been observed.

### Features

| Feature                        | Description                                                                                                                                                   |
| ------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Browse Photographs             | Browse PNG and JPEG images in the currently selected folder, adjust brightness, zoom and pan using scrollbars or drag controls without changing the originals |
| Point-and-Click Annotations    | Mark individual animals at their image positions using a point-and-click interface                                                                            |
| Flag Unknown Animals           | Mark unidentified individuals and flag images for further examination                                                                                         |
| Species Catalogue              | Maintain a species catalogue, holding the common and scientific names for each species and organising species into categories                                 |
| Species Filter                 | Filter images in the currently selected folder by an identified species to view or revise saved annotations                                                   |
| Species Search                 | Search for identified species across the database and browse matching images                                                                                  |
| Geographical Locations         | Maintain a catalogue of observation locations with names, regions, countries and optional latitude and longitude                                              |
| Folder Management              | Manage folder paths, footage dates and associated geographical locations, check image availability and remap folders that have been moved                     |
| Import and Export Observations | Import/export species identifications in CSV format                                                                                                           |
| Nature Recorder Tranfer        | Transfer sightings from the _ReefTag_ database to _Nature Recorder_                                                                                           |

### How It Works

The workflow is as follows:

1. Select a folder containing underwater photographs and set its footage date
2. Choose an image and examine it, adjusting brightness or zoom as necessary
3. Click on an animal and select an existing species or enter its common and scientific names, optionally assigning a category
4. If you cannot identify the animal yet, mark it as unknown and return to it later
5. Repeat for other animals, then move on to the next photograph

Identified animals are annotated with numbered markers, while those that are unidentified are marked with question marks. The underlying photograph remains unchanged.

## Getting Started

Please see the [Wiki](https://github.com/davewalker5/ReefTag/wiki) for the user guide, controls and further details.

## Authors

- **Dave Walker** - _Initial work_

## Feedback

To report an issue or suggest an improvement, please use the project's [GitHub Issues](https://github.com/davewalker5/ReefTag/issues) page.

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.

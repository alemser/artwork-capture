# Artwork Capture Project

This project aims to capture audio from a microphone on a Raspberry Pi running Moode, perform audio fingerprinting to identify the playing music, fetch album artwork via APIs, and display it on a connected screen.

## Features
- Audio capture from USB microphone
- Music fingerprinting using AcoustID
- Metadata and artwork retrieval from MusicBrainz API
- Image display on screen
- Integration with Moode audio player

## Requirements
- Raspberry Pi 4 Model B with 8GB RAM
- Moode Audio Player (latest version)
- USB microphone
- Display connected to Pi
- Python 3.7+

## Installation
1. Clone this repository on your Raspberry Pi.
2. Install dependencies: `pip install -r requirements.txt`
3. Run the main script: `python src/main.py`

## Usage
Connect the microphone and display. Run the script in the background: `source venv/bin/activate && python src/main.py &`

The script automatically detects playback mode:
- When streaming via AirPlay or UPnP (MPD playing), it skips processing.
- When playing analog sources (vinyl/CD), it captures audio, fingerprints, and displays artwork.
- Avoids processing when no audio is detected.

Adjust `MIC_DEVICE_INDEX`, `DISPLAY_WIDTH`, `DISPLAY_HEIGHT`, and audio threshold in the code as needed.
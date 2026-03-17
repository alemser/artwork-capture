import pyaudio
import wave
import acoustid
import requests
from mpd import MPDClient
import pygame
import time
import os
import logging
import tempfile
import subprocess

# Configuration
MIC_DEVICE_INDEX = 0  # Adjust based on your setup
CHUNK = 1024
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 44100
RECORD_SECONDS = 10  # Record 10 seconds for fingerprinting
API_KEY = os.environ.get('ACOUSTID_API_KEY', 'your_acoustid_api_key')  # Set via export ACOUSTID_API_KEY=...
DISPLAY_WIDTH = 800
DISPLAY_HEIGHT = 480

# Commands to stop/start Moode UI (lighttpd web server)
STOP_UI_CMD = ["sudo", "systemctl", "stop", "lighttpd"]
START_UI_CMD = ["sudo", "systemctl", "start", "lighttpd"]

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def record_audio():
    try:
        p = pyaudio.PyAudio()
        stream = p.open(format=FORMAT,
                        channels=CHANNELS,
                        rate=RATE,
                        input=True,
                        input_device_index=MIC_DEVICE_INDEX,
                        frames_per_buffer=CHUNK)

        logger.info("Recording...")
        frames = []

        for i in range(0, int(RATE / CHUNK * RECORD_SECONDS)):
            data = stream.read(CHUNK)
            frames.append(data)

        logger.info("Finished recording.")
        stream.stop_stream()
        stream.close()
        p.terminate()

        return b''.join(frames)
    except Exception as e:
        logger.error(f"Error recording audio: {e}")
        return None

def fingerprint_audio(audio_data):
    try:
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as temp_file:
            temp_path = temp_file.name
            with wave.open(temp_path, 'wb') as wf:
                wf.setnchannels(CHANNELS)
                wf.setsampwidth(2)  # 16-bit
                wf.setframerate(RATE)
                wf.writeframes(audio_data)

        duration, fp = acoustid.fingerprint_file(temp_path)
        os.unlink(temp_path)
        return fp
    except Exception as e:
        logger.error(f"Error fingerprinting audio: {e}")
        return None

def get_metadata(fingerprint):
    try:
        results = acoustid.lookup(API_KEY, fingerprint, duration=RECORD_SECONDS)
        if results['results']:
            recording = results['results'][0]
            return recording['recordings'][0] if recording['recordings'] else None
        return None
    except Exception as e:
        logger.error(f"Error getting metadata: {e}")
        return None

def get_artwork(recording):
    try:
        if 'releasegroups' in recording:
            rg = recording['releasegroups'][0]
            if 'releases' in rg:
                release = rg['releases'][0]
                if 'cover-art-archive' in release and release['cover-art-archive']['artwork']:
                    # Fetch front cover
                    mbid = release['id']
                    url = f"https://coverartarchive.org/release/{mbid}/front"
                    response = requests.get(url, timeout=10)
                    if response.status_code == 200:
                        return response.content
        return None
    except Exception as e:
        logger.error(f"Error getting artwork: {e}")
        return None

def display_image(image_data):
    try:
        # Stop UI to free the display
        logger.info("Stopping UI to access display")
        subprocess.run(STOP_UI_CMD, check=True)
        time.sleep(2)  # Wait for UI to stop

        screen = pygame.display.set_mode((DISPLAY_WIDTH, DISPLAY_HEIGHT))
        pygame.display.set_caption("Album Artwork")

        # Load image from bytes
        import io
        image = pygame.image.load(io.BytesIO(image_data))
        image = pygame.transform.scale(image, (DISPLAY_WIDTH, DISPLAY_HEIGHT))

        screen.blit(image, (0, 0))
        pygame.display.flip()

        # Keep displaying for some time or until quit
        running = True
        start_time = time.time()
        while running and time.time() - start_time < 30:  # Display for 30 seconds
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False

        pygame.display.quit()
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to stop UI: {e}")
    except Exception as e:
        logger.error(f"Error displaying image: {e}")
    finally:
        # Restart UI
        try:
            logger.info("Restarting UI")
            subprocess.run(START_UI_CMD, check=True)
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to start UI: {e}")

def has_audio(audio_data):
    # Check if the audio has significant sound
    import struct
    data = struct.unpack('<' + 'h' * (len(audio_data) // 2), audio_data)
    max_amplitude = max(abs(sample) for sample in data)
    threshold = 1000  # Adjust based on mic sensitivity
    return max_amplitude > threshold

def main():
    pygame.init()
    client = MPDClient()
    try:
        client.connect("localhost", 6600)  # Moode MPD port
        mpd_available = True
    except Exception as e:
        logger.warning(f"MPD not available: {e}")
        mpd_available = False

    while True:
        is_streaming = False
        if mpd_available:
            try:
                status = client.status()
                if status.get('state') == 'play':
                    is_streaming = True
            except Exception as e:
                logger.error(f"Error checking MPD status: {e}")

        if not is_streaming:
            # Check for analog playback
            audio_data = record_audio()
            if audio_data and has_audio(audio_data):
                fp = fingerprint_audio(audio_data)
                if fp:
                    recording = get_metadata(fp)
                    if recording:
                        artwork = get_artwork(recording)
                        if artwork:
                            display_image(artwork)
        time.sleep(30)  # Check every 30 seconds

if __name__ == "__main__":
    main()
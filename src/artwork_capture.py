import pyaudio
import wave
import acoustid
import requests
from mpd import MPDClient
import pygame
import time
import os
import logging
import logging.handlers
import tempfile
import subprocess
from datetime import datetime
import signal

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
LOG_FILE = 'artwork_capture.log'
LOG_MAX_SIZE = 1024 * 1024  # 1MB

# Commands to stop/start Moode UI (lighttpd web server)
STOP_UI_CMD = ["sudo", "systemctl", "stop", "lighttpd"]
START_UI_CMD = ["sudo", "systemctl", "start", "lighttpd"]

# Setup logging with file rotation
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Console handler
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
console_handler.setFormatter(console_formatter)
logger.addHandler(console_handler)

# File handler with rotation (1MB max)
file_handler = logging.handlers.RotatingFileHandler(
    LOG_FILE,
    maxBytes=LOG_MAX_SIZE,
    backupCount=5
)
file_handler.setLevel(logging.INFO)
file_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
file_handler.setFormatter(file_formatter)
logger.addHandler(file_handler)

def timeout_handler(signum, frame):
    raise TimeoutError("Recording timed out")

def record_audio():
    def _record():
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
            data = stream.read(CHUNK, exception_on_overflow=False)
            if not data:
                logger.warning("Audio buffer overflow detected, skipping chunk")
                continue
            frames.append(data)

        logger.info("Finished recording.")
        stream.stop_stream()
        stream.close()
        p.terminate()

        return b''.join(frames)

    try:
        signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(RECORD_SECONDS + 10)  # Timeout a bit longer than recording
        result = _record()
        signal.alarm(0)  # Cancel alarm
        return result
    except (Exception, TimeoutError) as e:
        logger.error(f"Error recording audio: {e}")
        signal.alarm(0)  # Ensure alarm is cancelled
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

def is_display_available():
    """Check if a display device is available"""
    try:
        # Try to detect display using pygame
        import os
        
        # Check for DISPLAY environment variable (X11/Wayland)
        if os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY'):
            return True
        
        # Try to initialize pygame to check for framebuffer/display
        try:
            pygame.init()
            pygame.display.set_mode((1, 1))
            pygame.display.quit()
            pygame.quit()
            return True
        except Exception:
            return False
    except Exception as e:
        logger.warning(f"Error checking display availability: {e}")
        return False

def get_mpd_status(client):
    """Get current MPD playback status"""
    try:
        status = client.status()
        state = status.get('state', 'stop')
        return state == 'play'
    except Exception:
        return False

def log_detected_music(recording, source='analog'):
    """Log detected music to file with metadata"""
    if not recording:
        return
    
    try:
        title = recording.get('title', 'Unknown Title')
        artists = recording.get('artists', [])
        artist_name = ', '.join([a.get('name', 'Unknown') for a in artists]) if artists else 'Unknown Artist'
        
        log_entry = f"DETECTED | Source: {source} | Artist: {artist_name} | Title: {title}"
        logger.info(log_entry)
    except Exception as e:
        logger.error(f"Error logging music: {e}")

def headless_mode(client):
    """Run in headless mode (no display) - logs detected music to file"""
    logger.info("=== HEADLESS MODE ===")
    logger.info("No display detected. Running in headless mode - logging music detections to file.")
    
    while True:
        is_streaming = False
        
        # Check if MPD is playing (streaming)
        try:
            if get_mpd_status(client):
                is_streaming = True
        except Exception as e:
            logger.error(f"Error checking MPD status: {e}")
        
        if is_streaming:
            logger.debug("Streaming via Moode detected - skipping analog source check")
        else:
            # Check for analog source
            audio_data = record_audio()
            if audio_data and has_audio(audio_data):
                logger.info("Audio detected from analog source")
                fp = fingerprint_audio(audio_data)
                if fp:
                    recording = get_metadata(fp)
                    if recording:
                        log_detected_music(recording, source='vinyl/CD')
                    else:
                        logger.info("DETECTED | Source: vinyl/CD | Music not found in database")
            else:
                logger.debug("No audio detected - silence")
        
        time.sleep(30)  # Check every 30 seconds

def has_audio(audio_data):
    # Check if the audio has significant sound
    import struct
    data = struct.unpack('<' + 'h' * (len(audio_data) // 2), audio_data)
    max_amplitude = max(abs(sample) for sample in data)
    threshold = 1000  # Adjust based on mic sensitivity
    return max_amplitude > threshold

def main():
    logger.info("Starting Artwork Capture")
    
    # Check microphone availability
    try:
        import pyaudio
        p = pyaudio.PyAudio()
        device_count = p.get_device_count()
        if device_count == 0:
            logger.error("No audio devices found. Exiting.")
            return
        logger.info(f"Found {device_count} audio device(s)")
        p.terminate()
    except Exception as e:
        logger.error(f"Error checking microphone: {e}")
        return
    
    # Connect to MPD
    client = MPDClient()
    try:
        client.connect("localhost", 6600)  # Moode MPD port
        logger.info("Connected to Moode MPD")
        mpd_available = True
    except Exception as e:
        logger.warning(f"MPD not available: {e}")
        mpd_available = False
    
    # Check for display
    display_available = is_display_available()
    logger.info(f"Display available: {display_available}")
    
    if not display_available:
        # Run in headless mode if no display
        logger.info("No display found - running in headless mode")
        headless_mode(client)
        return
    
    # Normal mode with display
    pygame.init()
    logger.info("Running in display mode")
    
    while True:
        is_streaming = False
        if mpd_available:
            try:
                if get_mpd_status(client):
                    is_streaming = True
            except Exception as e:
                logger.error(f"Error checking MPD status: {e}")

        if not is_streaming:
            # Check for analog playback
            audio_data = record_audio()
            if audio_data and has_audio(audio_data):
                logger.info("Audio detected from analog source")
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
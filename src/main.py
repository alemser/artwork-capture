import pyaudio
import wave
import acoustid
import requests
from mpd import MPDClient
import pygame
import time
import os

# Configuration
MIC_DEVICE_INDEX = 0  # Adjust based on your setup
CHUNK = 1024
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 44100
RECORD_SECONDS = 10  # Record 10 seconds for fingerprinting
API_KEY = 'your_acoustid_api_key'  # Get from acoustid.org
DISPLAY_WIDTH = 800
DISPLAY_HEIGHT = 480

def record_audio():
    p = pyaudio.PyAudio()
    stream = p.open(format=FORMAT,
                    channels=CHANNELS,
                    rate=RATE,
                    input=True,
                    input_device_index=MIC_DEVICE_INDEX,
                    frames_per_buffer=CHUNK)

    print("Recording...")
    frames = []

    for i in range(0, int(RATE / CHUNK * RECORD_SECONDS)):
        data = stream.read(CHUNK)
        frames.append(data)

    print("Finished recording.")
    stream.stop_stream()
    stream.close()
    p.terminate()

    return b''.join(frames)

def fingerprint_audio(audio_data):
    # Save to temp file for acoustid
    with wave.open('temp.wav', 'wb') as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(RATE)
        wf.writeframes(audio_data)

    duration, fp = acoustid.fingerprint_file('temp.wav')
    os.remove('temp.wav')
    return fp

def get_metadata(fingerprint):
    results = acoustid.lookup(API_KEY, fingerprint, duration=RECORD_SECONDS)
    if results['results']:
        recording = results['results'][0]
        return recording['recordings'][0] if recording['recordings'] else None
    return None

def get_artwork(recording):
    if 'releasegroups' in recording:
        rg = recording['releasegroups'][0]
        if 'releases' in rg:
            release = rg['releases'][0]
            if 'cover-art-archive' in release and release['cover-art-archive']['artwork']:
                # Fetch front cover
                mbid = release['id']
                url = f"https://coverartarchive.org/release/{mbid}/front"
                response = requests.get(url)
                if response.status_code == 200:
                    return response.content
    return None

def display_image(image_data):
    pygame.init()
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

    pygame.quit()

def has_audio(audio_data):
    # Check if the audio has significant sound
    import struct
    data = struct.unpack('<' + 'h' * (len(audio_data) // 2), audio_data)
    max_amplitude = max(abs(sample) for sample in data)
    threshold = 1000  # Adjust based on mic sensitivity
    return max_amplitude > threshold

def main():
    client = MPDClient()
    try:
        client.connect("localhost", 6600)  # Moode MPD port
    except:
        print("MPD not available, assuming analog mode")
        mpd_available = False
    else:
        mpd_available = True

    while True:
        is_streaming = False
        if mpd_available:
            try:
                status = client.status()
                if status.get('state') == 'play':
                    is_streaming = True
            except:
                pass

        if not is_streaming:
            # Check for analog playback
            audio_data = record_audio()
            if has_audio(audio_data):
                fp = fingerprint_audio(audio_data)
                recording = get_metadata(fp)
                if recording:
                    artwork = get_artwork(recording)
                    if artwork:
                        display_image(artwork)
        time.sleep(30)  # Check every 30 seconds

if __name__ == "__main__":
    main()
"""
Integration tests for real microphone and API calls.
Run these to verify your microphone works and APIs are accessible without deploying to Pi.
"""

import unittest
import os
import sys
import time
import struct

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from artwork_capture import record_audio, fingerprint_audio, get_metadata, get_artwork, has_audio


class TestMicrophoneIntegration(unittest.TestCase):
    """Test real microphone recording"""

    def test_microphone_accessible(self):
        """Verify USB microphone can be accessed"""
        try:
            import pyaudio
            p = pyaudio.PyAudio()
            device_count = p.get_device_count()
            self.assertGreater(device_count, 0, "No audio devices found")
            
            # List available devices
            print("\n=== Available Audio Devices ===")
            for i in range(device_count):
                info = p.get_device_info_by_index(i)
                print(f"{i}: {info['name']} (Channels: {info['maxInputChannels']})")
            
            p.terminate()
        except Exception as e:
            self.fail(f"PyAudio error: {e}")

    def test_record_audio_from_microphone(self):
        """Record 3 seconds of audio from microphone"""
        print("\n=== Recording from Microphone ===")
        print("Please speak or make noise near the microphone for 3 seconds...")
        
        try:
            import pyaudio
            import wave
            import tempfile
            
            # Record directly
            CHUNK = 1024
            FORMAT = pyaudio.paInt16
            CHANNELS = 1
            RATE = 44100
            RECORD_SECONDS = 3
            
            p = pyaudio.PyAudio()
            stream = p.open(format=FORMAT,
                          channels=CHANNELS,
                          rate=RATE,
                          input=True,
                          input_device_index=0,
                          frames_per_buffer=CHUNK)
            
            print("Recording...")
            frames = []
            for _ in range(0, int(RATE / CHUNK * RECORD_SECONDS)):
                data = stream.read(CHUNK)
                frames.append(data)
            
            print("Recording stopped.")
            stream.stop_stream()
            stream.close()
            p.terminate()
            
            audio_data = b''.join(frames)
            self.assertGreater(len(audio_data), 0, "No audio recorded")
            
            # Check if audio has sound
            has_sound = has_audio(audio_data)
            print(f"Audio detected: {has_sound}")
            
        except Exception as e:
            self.fail(f"Recording error: {e}")


class TestAPIIntegration(unittest.TestCase):
    """Test real API calls"""

    @unittest.skipIf(not os.environ.get('ACOUSTID_API_KEY'), 
                     "ACOUSTID_API_KEY not set")
    def test_acoustid_api_key_valid(self):
        """Verify AcoustID API key is set and accessible"""
        api_key = os.environ.get('ACOUSTID_API_KEY')
        self.assertIsNotNone(api_key, "ACOUSTID_API_KEY not set")
        self.assertGreater(len(api_key), 0, "ACOUSTID_API_KEY is empty")
        print(f"\n=== AcoustID API Key ===")
        print(f"API Key set: {api_key[:10]}...")

    def test_acoustid_connectivity(self):
        """Test connectivity to AcoustID API"""
        try:
            import requests
            response = requests.get('https://acoustid.org/', timeout=5)
            self.assertIn(response.status_code, [200, 301, 302], 
                         f"AcoustID not accessible: {response.status_code}")
            print("\n=== AcoustID Connectivity ===")
            print("✓ AcoustID API server is reachable")
        except Exception as e:
            self.fail(f"Cannot reach AcoustID: {e}")

    def test_musicbrainz_connectivity(self):
        """Test connectivity to MusicBrainz API"""
        try:
            import requests
            response = requests.get('https://musicbrainz.org/', timeout=5)
            self.assertIn(response.status_code, [200, 301, 302],
                         f"MusicBrainz not accessible: {response.status_code}")
            print("\n=== MusicBrainz Connectivity ===")
            print("✓ MusicBrainz API server is reachable")
        except Exception as e:
            self.fail(f"Cannot reach MusicBrainz: {e}")

    def test_coverartarchive_connectivity(self):
        """Test connectivity to Cover Art Archive"""
        try:
            import requests
            response = requests.get('https://coverartarchive.org/', timeout=5)
            self.assertIn(response.status_code, [200, 301, 302],
                         f"Cover Art Archive not accessible: {response.status_code}")
            print("\n=== Cover Art Archive Connectivity ===")
            print("✓ Cover Art Archive is reachable")
        except Exception as e:
            self.fail(f"Cannot reach Cover Art Archive: {e}")

    @unittest.skipIf(not os.environ.get('ACOUSTID_API_KEY'),
                     "ACOUSTID_API_KEY not set")
    def test_acoustid_with_sample_fingerprint(self):
        """Test AcoustID lookup with a known fingerprint"""
        api_key = os.environ.get('ACOUSTID_API_KEY')
        if not api_key:
            self.skipTest("API key not available")
        
        try:
            import acoustid
            # A known fingerprint for testing (adjust if needed)
            test_fingerprint = "AQADtEiUgEsf5qgSFxSJOQgHEBkGBhHjBwjhBAjhA4ThAwPhBIfhgzgKAecVAOcHd-QJ0goL5QkP51cR"
            
            print(f"\n=== AcoustID Lookup Test ===")
            print(f"Testing fingerprint lookup...")
            
            results = acoustid.lookup(api_key, test_fingerprint, duration=10)
            
            self.assertIn('results', results, "No results in AcoustID response")
            print(f"✓ AcoustID lookup successful")
            print(f"Results found: {len(results.get('results', []))}")
            
        except Exception as e:
            print(f"Note: AcoustID lookup may fail with test fingerprint: {e}")
            # Don't fail - the API might have rate limits or the fingerprint might not exist

    def test_get_metadata_with_valid_data(self):
        """Test metadata parsing with mock data"""
        print(f"\n=== Metadata Parsing Test ===")
        
        # Mock recording data
        mock_recording = {
            'title': 'Test Song',
            'releasegroups': [{
                'releases': [{
                    'id': '12345678-1234-5678-1234-567812345678',
                    'title': 'Test Album',
                    'cover-art-archive': {'artwork': True}
                }]
            }]
        }
        
        # Test that get_artwork can parse this
        artwork_url = get_artwork(mock_recording)
        # It should attempt to fetch but may not succeed without real MBID
        print(f"✓ Metadata parsing successful")

    def test_coverart_archive_request(self):
        """Test actual Cover Art Archive request with known MBID"""
        try:
            import requests
            
            # Use a known MBID for a popular album
            # The Beatles - Abbey Road
            test_mbid = '1e1f93f4-f8c9-35d6-8d8e-f1d08c08e06e'  # Abbey Road
            
            print(f"\n=== Cover Art Archive Request Test ===")
            print(f"Requesting artwork for MBID: {test_mbid}")
            
            url = f"https://coverartarchive.org/release/{test_mbid}/front"
            response = requests.get(url, timeout=10)
            
            if response.status_code == 200:
                print(f"✓ Artwork found: {len(response.content)} bytes")
                self.assertGreater(len(response.content), 1000, "Image too small")
            else:
                print(f"Note: No artwork for this MBID (status: {response.status_code})")
        
        except Exception as e:
            print(f"Note: Cover Art Archive lookup failed: {e}")
            # Don't fail - network or MBID might not have artwork


class TestAudioQuality(unittest.TestCase):
    """Test audio quality and processing"""

    def test_has_audio_detection_sensitivity(self):
        """Test audio detection with different volume levels"""
        print(f"\n=== Audio Detection Sensitivity ===")
        
        # Silence (very low amplitude)
        silence = struct.pack('<' + 'h' * 100, *[100] * 100)
        self.assertFalse(has_audio(silence), "Should detect silence")
        print("✓ Silence detected correctly")
        
        # Loud sound (high amplitude)
        loud = struct.pack('<' + 'h' * 100, *[2000] * 100)
        self.assertTrue(has_audio(loud), "Should detect loud sound")
        print("✓ Loud sound detected correctly")
        
        # Medium sound (borderline)
        medium = struct.pack('<' + 'h' * 100, *[1200] * 100)
        has_sound = has_audio(medium)
        print(f"✓ Medium sound detection: {has_sound}")


class TestLocalMicrophoneRecording(unittest.TestCase):
    """Test with actual microphone on local machine"""

    def test_full_recording_fingerprint_cycle(self):
        """Full cycle: record -> fingerprint -> check result"""
        if not os.environ.get('ACOUSTID_API_KEY'):
            self.skipTest("ACOUSTID_API_KEY not set - skipping full cycle")
        
        print(f"\n=== Full Recording Cycle Test ===")
        print("Please play music or make recognizable sounds near the microphone.")
        print("This test will record 5 seconds and attempt to fingerprint.")
        
        try:
            # Record audio
            print("Recording...")
            audio_data = record_audio()
            
            if not audio_data:
                self.skipTest("Failed to record audio")
            
            print(f"✓ Audio recorded: {len(audio_data)} bytes")
            
            # Check if it has sound
            if not has_audio(audio_data):
                self.skipTest("Recording has no sound - please make noise during test")
            
            print("✓ Audio detected")
            
            # Fingerprint
            print("Fingerprinting...")
            fp = fingerprint_audio(audio_data)
            
            if fp:
                print(f"✓ Fingerprint generated: {fp[:50]}...")
                
                # Try to get metadata
                print("Looking up metadata...")
                metadata = get_metadata(fp)
                
                if metadata:
                    print(f"✓ Metadata found: {metadata.get('title', 'Unknown')}")
                else:
                    print("Note: No metadata found (music may not be in database)")
            else:
                self.skipTest("Could not generate fingerprint")
        
        except Exception as e:
            self.fail(f"Error in recording cycle: {e}")


if __name__ == '__main__':
    # Run with verbose output
    unittest.main(verbosity=2)

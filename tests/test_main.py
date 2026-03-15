import unittest
from unittest.mock import patch, MagicMock
import struct
import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from artwork_capture import has_audio, fingerprint_audio, get_metadata, get_artwork

class TestArtworkCapture(unittest.TestCase):

    def test_has_audio_with_sound(self):
        # Create dummy audio data with high amplitude
        data = struct.pack('<' + 'h' * 100, *[2000] * 100)
        self.assertTrue(has_audio(data))

    def test_has_audio_without_sound(self):
        # Create dummy audio data with low amplitude
        data = struct.pack('<' + 'h' * 100, *[500] * 100)
        self.assertFalse(has_audio(data))

    @patch('os.unlink')
    @patch('acoustid.fingerprint_file')
    @patch('tempfile.NamedTemporaryFile')
    @patch('wave.open')
    def test_fingerprint_audio_success(self, mock_wave_open, mock_temp, mock_fp, mock_unlink):
        mock_temp.return_value.__enter__.return_value.name = 'temp.wav'
        mock_wave_open.return_value.__enter__.return_value = MagicMock()  # Mock file
        mock_fp.return_value = (10.0, 'fingerprint')
        
        audio_data = b'dummy'
        result = fingerprint_audio(audio_data)
        self.assertEqual(result, 'fingerprint')

    @patch('os.unlink')
    @patch('acoustid.fingerprint_file')
    @patch('tempfile.NamedTemporaryFile')
    @patch('wave.open')
    def test_fingerprint_audio_error(self, mock_wave_open, mock_temp, mock_fp, mock_unlink):
        mock_temp.return_value.__enter__.return_value.name = 'temp.wav'
        mock_wave_open.return_value.__enter__.return_value = MagicMock()
        mock_fp.side_effect = Exception("Error")
        
        audio_data = b'dummy'
        result = fingerprint_audio(audio_data)
        self.assertIsNone(result)

    @patch('acoustid.lookup')
    def test_get_metadata_success(self, mock_lookup):
        mock_lookup.return_value = {'results': [{'recordings': [{'title': 'Test'}]}]}
        result = get_metadata('fp')
        self.assertEqual(result['title'], 'Test')

    @patch('acoustid.lookup')
    def test_get_metadata_no_results(self, mock_lookup):
        mock_lookup.return_value = {'results': []}
        result = get_metadata('fp')
        self.assertIsNone(result)

    @patch('requests.get')
    def test_get_artwork_success(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'image_data'
        mock_get.return_value = mock_response
        
        recording = {'releasegroups': [{'releases': [{'id': '123', 'cover-art-archive': {'artwork': True}}]}]}
        result = get_artwork(recording)
        self.assertEqual(result, b'image_data')

    @patch('requests.get')
    def test_get_artwork_no_artwork(self, mock_get):
        recording = {'releasegroups': [{'releases': [{'id': '123', 'cover-art-archive': {'artwork': False}}]}]}
        result = get_artwork(recording)
        self.assertIsNone(result)

if __name__ == '__main__':
    unittest.main()
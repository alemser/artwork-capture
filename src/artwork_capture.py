import os
import time
import logging
import subprocess
import tempfile
import requests
import numpy as np
import wave
import acoustid
import pygame
from mpd import MPDClient, ConnectionError
from scipy import signal

# --- Configurações Otimizadas ---
MIC_DEVICE_INDEX = 3
RECORD_SECONDS = 10
API_KEY = os.environ.get('ACOUSTID_API_KEY', 'your_key_here')
DISPLAY_RES = (800, 480)
CHECK_INTERVAL = 30 # Segundos entre scans

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.FileHandler('artwork_capture.log'), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

class AudioMonitor:
    def __init__(self):
        self.client = MPDClient()
        self.session = requests.Session()
        self.mpd_connected = False

    def connect_mpd(self):
        try:
            self.client.connect("localhost", 6600)
            self.mpd_connected = True
        except Exception as e:
            logger.debug(f"MPD Offline: {e}")
            self.mpd_connected = False

    def is_mpd_playing(self):
        try:
            if not self.mpd_connected: self.connect_mpd()
            return self.client.status().get('state') == 'play'
        except (ConnectionError, Exception):
            self.mpd_connected = False
            return False

    def record_and_verify(self):
        """Grava e verifica se há música de fato no sinal"""
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp:
            path = tmp.name

        cmd = ['arecord', '-D', f'hw:{MIC_DEVICE_INDEX},0', '-f', 'S16_LE', '-c', '1', '-r', '44100', '-d', str(RECORD_SECONDS), path]
        
        try:
            subprocess.run(cmd, capture_output=True, timeout=RECORD_SECONDS + 2)
            
            # Análise de Áudio (DSP)
            with wave.open(path, 'rb') as wf:
                data = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16)
            
            # 1. Check de Amplitude mínima (silêncio absoluto)
            if np.max(np.abs(data)) < 500:
                return None
            
            # 2. Check de Frequência (evitar ruído de 60Hz ou estática)
            freqs, psd = signal.welch(data, fs=44100)
            if np.sum(psd > (np.max(psd) * 0.01)) / len(psd) < 0.10:
                return None
                
            return path
        except Exception as e:
            logger.error(f"Erro na captura: {e}")
            return None

    def get_metadata_and_art(self, path):
        try:
            duration, fp = acoustid.fingerprint_file(path)
            res = acoustid.lookup(API_KEY, fp, duration)
            
            if res['results']:
                best_match = res['results'][0]
                if 'recordings' in best_match:
                    rec = best_match['recordings'][0]
                    title = rec.get('title')
                    artist = rec.get('artists', [{}])[0].get('name')
                    
                    # Busca Capa (Cover Art Archive)
                    mbid = rec.get('releasegroups', [{}])[0].get('id')
                    art_url = f"https://coverartarchive.org/release-group/{mbid}/front"
                    img_res = self.session.get(art_url, timeout=5)
                    
                    if img_res.status_code == 200:
                        return {"title": title, "artist": artist, "img": img_res.content}
            return None
        except Exception as e:
            logger.error(f"Erro no Fingerprint/Capa: {e}")
            return None

    def display_art(self, art_data):
        """Exibe a capa usando Pygame"""
        try:
            # Tenta inicializar o frame buffer se estiver no console
            if not os.environ.get('DISPLAY'):
                os.environ["SDL_VIDEODRIVER"] = "dummy" # Fallback
            
            pygame.display.init()
            screen = pygame.display.set_mode(DISPLAY_RES)
            
            import io
            img = pygame.image.load(io.BytesIO(art_data['img']))
            img = pygame.transform.scale(img, DISPLAY_RES)
            
            screen.blit(img, (0, 0))
            pygame.display.flip()
            logger.info(f"Exibindo: {art_data['artist']} - {art_data['title']}")
            time.sleep(25) # Mantém na tela
            pygame.display.quit()
        except Exception as e:
            logger.error(f"Erro ao exibir imagem: {e}")

    def run(self):
        logger.info("Monitor de Áudio Analógico iniciado.")
        while True:
            # Se o Moode já está tocando algo digital, ignora o analógico
            if self.is_mpd_playing():
                logger.debug("Moode está em uso (Streaming/Digital).")
            else:
                audio_path = self.record_and_verify()
                if audio_path:
                    data = self.get_metadata_and_art(audio_path)
                    if data:
                        self.display_art(data)
                    os.unlink(audio_path)
            
            time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    monitor = AudioMonitor()
    monitor.run()
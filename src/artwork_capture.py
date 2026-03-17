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

# --- CONFIGURAÇÕES ---
MIC_DEVICE_INDEX = 3
RECORD_SECONDS = 10
# Substitua pela sua chave real ou defina a variável de ambiente
API_KEY = os.environ.get('ACOUSTID_API_KEY', 'your_acoustid_api_key') 
DISPLAY_RES = (800, 480)
CHECK_INTERVAL = 20  # Reduzi para checar mais rápido
THRESHOLD_RATIO = 0.15  # Ajustado de 0.30 para 0.15 (mais sensível para o seu Rega)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.FileHandler('artwork_capture.log'), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

class MoodeAudioMonitor:
    def __init__(self):
        self.client = MPDClient()
        self.session = requests.Session()
        self.mpd_connected = False

    def connect_mpd(self):
        """Tenta conectar ao MPD com timeout curto para não travar"""
        try:
            self.client.timeout = 5
            self.client.connect("localhost", 6600)
            self.mpd_connected = True
            logger.info("Conectado ao MPD do Moode.")
        except Exception as e:
            logger.debug(f"Aguardando MPD ficar disponível... {e}")
            self.mpd_connected = False

    def should_scan_analog(self):
        """Verifica se o MPD está ocioso para permitir o scan do Vinil"""
        try:
            if not self.mpd_connected:
                self.connect_mpd()
            
            status = self.client.status()
            state = status.get('state')
            
            # Se estiver tocando rádio/FLAC/Spotify no Moode, não faz o scan
            if state == 'play':
                # Se houver uma música com título, é streaming digital
                song = self.client.currentsong()
                if song and 'title' in song:
                    logger.debug("MPD tocando música digital. Ignorando analógico.")
                    return False
            
            return True # MPD parado, pausado ou em 'play' vazio (comum no Moode)
        except (ConnectionError, Exception):
            self.mpd_connected = False
            return True

    def record_audio(self):
        """Captura áudio do hardware ALSA"""
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp:
            path = tmp.name

        cmd = [
            'arecord', '-D', f'hw:{MIC_DEVICE_INDEX},0', 
            '-f', 'S16_LE', '-c', '1', '-r', '44100', 
            '-d', str(RECORD_SECONDS), path
        ]
        
        try:
            subprocess.run(cmd, capture_output=True, timeout=RECORD_SECONDS + 2)
            return path
        except Exception as e:
            logger.error(f"Erro no arecord: {e}")
            return None

    def is_music(self, path):
        """Analisa se o sinal grav
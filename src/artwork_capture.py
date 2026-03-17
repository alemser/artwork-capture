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

# --- CONFIGURACOES ---
MIC_DEVICE_INDEX = 3
RECORD_SECONDS = 15
API_KEY = os.environ.get('ACOUSTID_API_KEY', 'your_acoustid_api_key') 
DISPLAY_RES = (800, 480)
CHECK_INTERVAL = 15
THRESHOLD_RATIO = 0.02 

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)

class MoodeAudioMonitor:
    def __init__(self):
        self.client = MPDClient()
        self.session = requests.Session()
        self.mpd_connected = False

    def connect_mpd(self):
        try:
            self.client.timeout = 5
            self.client.connect("localhost", 6600)
            self.mpd_connected = True
            logger.info("Conectado ao MPD.")
        except Exception:
            self.mpd_connected = False

    def should_scan_analog(self):
        try:
            if not self.mpd_connected:
                self.connect_mpd()
            status = self.client.status()
            if status.get('state') == 'play':
                song = self.client.currentsong()
                if song and 'title' in song:
                    return False
            return True
        except (ConnectionError, Exception):
            self.mpd_connected = False
            return True

    def record_audio(self):
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp:
            path = tmp.name
        
        # Gravamos normalmente
        cmd = [
            'arecord', '-D', f'hw:{MIC_DEVICE_INDEX},0', 
            '-f', 'S16_LE', '-c', '1', '-r', '44100', 
            '-d', str(RECORD_SECONDS), path
        ]
        
        try:
            subprocess.run(cmd, capture_output=True, timeout=RECORD_SECONDS + 5)
            
            # --- NOVO: Aumentar volume digitalmente em 10x ---
            # Isso ajuda o AcoustID a "ouvir" melhor o seu Rega
            try:
                # Se tiver o sox instalado: sudo apt install sox
                subprocess.run(['sox', '-v', '5.0', path, path + '_loud.wav'], capture_output=True)
                os.rename(path + '_loud.wav', path)
            except:
                pass 
                
            return path
        except Exception as e:
            logger.error(f"Erro no arecord: {e}")
            return None

    def is_music(self, path):
        try:
            with wave.open(path, 'rb') as wf:
                data = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16)
            max_amp = np.max(np.abs(data))
            freqs, psd = signal.welch(data, fs=44100)
            music_ratio = np.sum(psd > (np.max(psd) * 0.01)) / len(psd)
            logger.info(f"Sinal: Amp={max_amp} | Ratio={music_ratio:.4f}")
            return music_ratio > THRESHOLD_RATIO
        except Exception as e:
            logger.error(f"Erro no DSP: {e}")
            return False

    def get_artwork(self, path):
        if API_KEY == 'your_acoustid_api_key' or not API_KEY:
            logger.error("ERRO: Voce precisa configurar sua API_KEY do AcoustID!")
            return None

        try:
            # Fingerprint local
            duration, fp = acoustid.fingerprint_file(path)
            
            # Consulta ao servidor
            res = acoustid.lookup(API_KEY, fp, duration)
            
            # Verifica se o servidor retornou erro (ex: chave invalida)
            if res.get('status') != 'ok':
                logger.error(f"Erro no Servidor AcoustID: {res.get('error', 'Desconhecido')}")
                return None

            if 'results' in res and res['results']:
                best_match = res['results'][0]
                recs = best_match.get('recordings', [])
                if recs:
                    title = recs[0].get('title', 'Unknown')
                    artist = recs[0].get('artists', [{}])[0].get('name', 'Unknown')
                    logger.info(f"Identificado: {artist} - {title}")
                    
                    rgs = recs[0].get('releasegroups', [])
                    if rgs:
                        mbid = rgs[0].get('id')
                        url = f"https://coverartarchive.org/release-group/{mbid}/front"
                        img_res = self.session.get(url, timeout=5)
                        if img_res.status_code == 200:
                            return {"title": title, "img": img_res.content}
            else:
                logger.info("Musica ouvida, mas nao encontrada no banco de dados.")
            return None
        except Exception as e:
            logger.error(f"Erro no Processo AcoustID: {e}")
            return None

    def display_image(self, art_data):
        try:
            if not pygame.display.get_init():
                pygame.display.init()
            screen = pygame.display.set_mode(DISPLAY_RES)
            import io
            img = pygame.image.load(io.BytesIO(art_data['img']))
            img = pygame.transform.scale(img, DISPLAY_RES)
            screen.blit(img, (0, 0))
            pygame.display.flip()
            logger.info(f"Exibindo: {art_data['title']}")
            time.sleep(25) 
            pygame.display.quit()
        except Exception as e:
            logger.error(f"Erro Display: {e}")

    def start(self):
        logger.info("Monitor Analógico Iniciado.")
        while True:
            if self.should_scan_analog():
                path = self.record_audio()
                if path:
                    if self.is_music(path):
                        art = self.get_artwork(path)
                        if art:
                            self.display_image(art)
                    os.unlink(path)
            time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    monitor = MoodeAudioMonitor()
    monitor.start()
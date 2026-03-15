# Artwork Capture Project

Este projeto captura áudio de um microfone em um Raspberry Pi rodando Moode ou Volumio, realiza fingerprinting de áudio para identificar a música tocando, busca artwork de álbuns via APIs e exibe em uma tela conectada. É totalmente automático e transparente para o usuário.

## Funcionalidades
- Captura de áudio via microfone USB
- Fingerprinting de música usando AcoustID
- Recuperação de metadados e artwork via API do MusicBrainz
- Exibição de imagem na tela
- Integração com players Moode/Volumio (baseados em MPD)
- Gerenciamento automático de display único (para/ reinicia UI do player)

## Requisitos
- Raspberry Pi 4 Model B com 8GB RAM (ou similar)
- Moode Audio Player (versão mais recente) ou Volumio
- Microfone USB
- Tela conectada (HDMI ou similar)
- Python 3.7+
- Chave de API do AcoustID (gratuita, obtenha em acoustid.org)

## Instalação Passo a Passo

1. **Clone o repositório no seu Raspberry Pi:**
   ```
   git clone https://github.com/seu-usuario/artwork-capture.git
   cd artwork-capture
   ```

2. **Crie e ative um ambiente virtual:**
   ```
   python3 -m venv venv
   source venv/bin/activate
   ```

3. **Instale as dependências:**
   ```
   pip install -r requirements.txt
   ```

4. **Configure a chave da API do AcoustID:**
   - Obtenha uma chave gratuita em [acoustid.org](https://acoustid.org/).
   - Defina a variável de ambiente:
     ```
     export ACOUSTID_API_KEY=sua_chave_aqui
     ```
   - Para persistir, adicione ao seu `~/.bashrc` ou `~/.profile`:
     ```
     echo 'export ACOUSTID_API_KEY=sua_chave_aqui' >> ~/.bashrc
     source ~/.bashrc
     ```

5. **Configure permissões para gerenciamento de display (opcional, para tela única):**
   - Adicione o usuário ao grupo sudo (se necessário):
     ```
     sudo usermod -aG sudo pi
     ```
   - Ou rode o script com sudo (não recomendado para produção).

## Configuração

Edite `src/artwork_capture.py` para ajustar:
- `MIC_DEVICE_INDEX`: Índice do dispositivo de microfone (use `python3 -c "import pyaudio; p = pyaudio.PyAudio(); [print(f'{i}: {p.get_device_info_by_index(i)[\"name\"]}') for i in range(p.get_device_count())]"` para listar dispositivos).
- `DISPLAY_WIDTH` e `DISPLAY_HEIGHT`: Resolução da tela.
- `STOP_UI_CMD` e `START_UI_CMD`: Comandos para parar/iniciar a UI do player.
  - Para Moode: `["sudo", "systemctl", "stop", "lighttpd"]` e `["sudo", "systemctl", "start", "lighttpd"]`
  - Para Volumio: `["sudo", "systemctl", "stop", "volumio"]` e `["sudo", "systemctl", "start", "volumio"]`
- `RECORD_SECONDS`: Duração da gravação (10 segundos por padrão).
- `RATE`, `CHUNK`, etc.: Ajustes de áudio se necessário.

## Uso

1. Conecte o microfone USB e a tela ao Pi.
2. Certifique-se de que o Moode/Volumio está rodando e MPD ativo na porta 6600.
3. Rode o script em background:
   ```
   source venv/bin/activate
   nohup python src/artwork_capture.py &
   ```
4. O script monitora automaticamente:
   - Se MPD estiver tocando (streaming), pula o processamento.
   - Se não estiver (fonte analógica), grava áudio, verifica se há som, faz fingerprinting, busca artwork e exibe por 30 segundos.
   - Para tela única, para a UI do player temporariamente e reinicia depois.

## Testes

Para executar os testes:
```
source venv/bin/activate
python -m pytest tests/
```

## Troubleshooting

### Problema: Script não encontra microfone
- Verifique dispositivos: `python3 -c "import pyaudio; p = pyaudio.PyAudio(); [print(f'{i}: {p.get_device_info_by_index(i)[\"name\"]}') for i in range(p.get_device_count())]"`
- Ajuste `MIC_DEVICE_INDEX` no código.

### Problema: Erro de conexão com MPD
- Certifique-se de que Moode/Volumio está rodando e MPD na porta 6600.
- Verifique logs: o script loga erros.

### Problema: Display não funciona ou conflita
- Para tela única: confirme que `STOP_UI_CMD` e `START_UI_CMD` estão corretos.
- Rode com sudo se necessário: `sudo -E python src/artwork_capture.py` (preserva env vars).
- Se pygame falhar, verifique se a tela suporta gráficos (use HDMI com saída gráfica).

### Problema: Fingerprinting falha
- Verifique chave da API: `echo $ACOUSTID_API_KEY`
- Teste conectividade: `ping acoustid.org`
- Música muito baixa? Ajuste threshold em `has_audio()`.

### Problema: Artwork não encontrado
- Nem todas as músicas têm artwork no MusicBrainz.
- Verifique logs para erros de API.

### Problema: Script consome muita CPU/memória
- Reduza `RECORD_SECONDS` ou aumente intervalo de checagem (30s por padrão).
- Rode em background com `nice`.

### Problema: Não roda em boot

#### Opção 1 — Crontab (rápido)
1. Abra o crontab do usuário (geralmente `pi` no Raspbian/Moode):
   ```bash
   crontab -e
   ```
2. Adicione esta linha (ajuste o caminho para o seu projeto):
   ```bash
   @reboot cd /path/to/project && source venv/bin/activate && nohup python src/artwork_capture.py &
   ```

#### Opção 2 — Serviço systemd (recomendado)
1. Crie um arquivo de serviço como `/etc/systemd/system/artwork-capture.service` (use sudo):
   ```ini
   [Unit]
   Description=Artwork Capture
   After=network.target

   [Service]
   Type=simple
   WorkingDirectory=/path/to/project
   Environment=ACOUSTID_API_KEY=your_acoustid_api_key
   ExecStart=/path/to/project/venv/bin/python /path/to/project/src/artwork_capture.py
   Restart=on-failure
   User=pi

   [Install]
   WantedBy=multi-user.target
   ```
2. Habilite e inicie o serviço:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable artwork-capture.service
   sudo systemctl start artwork-capture.service
   ```
3. Verifique o status/logs:
   ```bash
   sudo systemctl status artwork-capture.service
   sudo journalctl -u artwork-capture.service -f
   ```

### Logs
- Logs são salvos no console. Para arquivo: `python src/artwork_capture.py > log.txt 2>&1 &`
- Nível de log: INFO por padrão; mude para DEBUG em `logging.basicConfig(level=logging.DEBUG)`.

Se problemas persistirem, verifique os logs e poste no repositório com detalhes do erro.

Adjust `MIC_DEVICE_INDEX`, `DISPLAY_WIDTH`, `DISPLAY_HEIGHT`, and audio threshold in the code as needed.
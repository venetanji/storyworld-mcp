from pathlib import Path
from mcp_server import config, downloader
import yaml

print('CHARACTERS_DESC_DIR =', config.CHARACTERS_DESC_DIR)
print('CHARACTERS_IMAGE_DIR =', config.CHARACTERS_IMAGE_DIR)
print('IMAGES_DIR =', config.IMAGES_DIR)

print('\nDescriptions (first 20):')
for i, p in enumerate(sorted(config.CHARACTERS_DESC_DIR.glob('*.yaml'))[:20]):
    print(' ', i+1, p.name)

print('\nImages (first 50 recursive):')
imgs = list(config.CHARACTERS_IMAGE_DIR.rglob('*'))
print(' total found under images dir:', len(imgs))
for p in imgs[:50]:
    print(' ', p.relative_to(config.CHARACTERS_IMAGE_DIR))

# Print HF dataset env/default
print('\nHF_IMAGES_DATASET =', config.HF_IMAGES_DATASET)

# Do NOT call snapshot_download here automatically; show how to call fetch_all manually:
print('\nTo download images run:')
print(' python -m mcp_server.downloader')

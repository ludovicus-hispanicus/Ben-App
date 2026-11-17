# Kraken models shipped with the BEn installers

The Mac build (`.github/workflows/build-mac.yml`) copies these files into
`server/src/cured_models/` before packaging the server, because that folder is
not in git. `active_model.txt` names the model BEn uses by default.

- `CUSAS18.safetensors`: Kraken 7.1 (PP-OCRv6), trained on CUSAS 18, 98.1 %
  character accuracy on its validation lines (BEn 2.0.0).

# BEn News

## 2026-11-17 — BEn 2.0 released
BEn 2.0 is the basic version of BEn: CuReD (OCR of transliterations in print editions) and the Library. Download it from the [release page](https://github.com/ludovicus-hispanicus/Ben-App/releases/latest).

- **Kraken 7.1** with a new CUSAS 18 model (98.1% of characters right on its validation lines). Train your own Kraken models from the texts you corrected. Without a graphics card training works, but slowly.
- **Layout detection inside CuReD:** find the regions of a dictionary page (entries, headers, page numbers) and send one to OCR with a click. Layout training is a CuReD tab and offers YOLO26.
- **Ollama models found automatically:** CuReD lists the installed models that can read images, Ollama's cloud models, and models to download, with their size. Long dictionary entries are no longer cut off halfway.
- **Current model lists from Gemini, Claude, OpenAI and Grok**, including "always latest" options.
- **Faster:** Kraken is ready as soon as BEn starts, uses the graphics card when it is free, and the Library and text lists load faster.
- **Easier navigation:** a back button with the path of where you are, and the browser's back button follows it.
- **For users who run BEn from source with an NVIDIA graphics card:** train DeepSeek-OCR on your corrected texts and use it in CuReD through Ollama.

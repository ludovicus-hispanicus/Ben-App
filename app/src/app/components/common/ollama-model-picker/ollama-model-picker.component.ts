import { Component, EventEmitter, NgZone, OnDestroy, Output } from '@angular/core';
import { CuredService, OllamaCatalog, OllamaVisionModel } from 'src/app/services/cured.service';

interface Download {
  name: string;
  totalGb: number | null;
  doneGb: number;
  status: string;
  error: string | null;
}

/**
 * Dropdown of Ollama models: the installed ones, Ollama's cloud models, and the
 * vision models that can be downloaded from ollama.com. Both lists are fetched the
 * first time the dropdown is opened (and again on "Refresh"). A download is only
 * started after confirming its size, and its progress is shown below the dropdown.
 */
@Component({
  selector: 'app-ollama-model-picker',
  templateUrl: './ollama-model-picker.component.html',
  styleUrls: ['./ollama-model-picker.component.scss']
})
export class OllamaModelPickerComponent implements OnDestroy {
  /** The exact Ollama name of the chosen model, e.g. "qwen3-vl:4b". */
  @Output() picked = new EventEmitter<string>();

  loaded = false;
  loading = false;
  ollamaAvailable = true;
  usable: OllamaVisionModel[] = [];
  notUsable: Array<{ name: string; reason: string }> = [];

  catalog: OllamaCatalog | null = null;
  catalogLoading = false;
  cloudOffers: OllamaCatalog['cloud'] = [];
  downloadOffers: OllamaCatalog['downloads'] = [];
  // What the dropdown shows: the suggestions first, then the rest of each kind
  suggestedOffers: Array<{ name: string; detail: string; description?: string }> = [];
  otherCloudOffers: OllamaCatalog['cloud'] = [];
  otherDownloadOffers: OllamaCatalog['downloads'] = [];

  download: Download | null = null;
  private eventSource: EventSource | null = null;

  readonly RELOAD = '__reload__';

  constructor(private curedService: CuredService, private zone: NgZone) {}

  ngOnDestroy(): void {
    this.eventSource?.close();
  }

  onOpenedChange(open: boolean): void {
    if (open && !this.loaded && !this.loading) {
      this.load(false);
    }
  }

  /** Installed models from the local Ollama, and the offers from ollama.com. */
  load(refreshCatalog: boolean): void {
    this.loading = true;
    this.curedService.getOllamaVisionModels().subscribe({
      next: (response) => {
        this.ollamaAvailable = response.ollama_available;
        this.usable = response.models;
        this.notUsable = [
          ...(response.text_only || []).map(m => ({ name: m.name, reason: 'no image input' })),
          ...response.unavailable.map(m => ({ name: m.name, reason: m.error })),
        ];
        this.loaded = true;
        this.loading = false;
        this.updateOffers();
      },
      error: () => {
        this.ollamaAvailable = false;
        this.loaded = true;
        this.loading = false;
      }
    });

    this.catalogLoading = true;
    this.curedService.getOllamaCatalog(refreshCatalog).subscribe({
      next: (catalog) => {
        this.catalog = catalog;
        this.catalogLoading = false;
        this.updateOffers();
      },
      error: () => { this.catalogLoading = false; }
    });
  }

  /** Offer only what isn't installed yet. */
  private updateOffers(): void {
    if (!this.catalog) return;
    const installed = new Set([...this.usable.map(m => m.name), ...this.notUsable.map(m => m.name)]);
    this.cloudOffers = this.catalog.cloud.filter(m => !installed.has(m.name));
    this.downloadOffers = this.catalog.downloads.filter(m => !installed.has(m.name));
    this.suggestedOffers = [
      ...this.downloadOffers.filter(m => m.suggested)
        .map(m => ({ name: m.name, detail: `${m.size_gb} GB download`, description: m.description })),
      ...this.cloudOffers.filter(m => m.suggested).map(m => ({ name: m.name, detail: 'cloud, no download' })),
    ];
    this.otherCloudOffers = this.cloudOffers.filter(m => !m.suggested);
    this.otherDownloadOffers = this.downloadOffers.filter(m => !m.suggested);
  }

  onSelect(value: string | null): void {
    if (!value) return;
    if (value === this.RELOAD) {
      this.load(true);
      return;
    }
    if (this.usable.some(m => m.name === value)) {
      this.picked.emit(value);
      return;
    }
    const cloud = this.cloudOffers.find(m => m.name === value);
    if (cloud) {
      // A cloud model is added to Ollama as a tiny entry (no model download)
      this.pull(value, null);
      return;
    }
    const offer = this.downloadOffers.find(m => m.name === value);
    if (offer && confirm(
      `Download ${offer.name} from Ollama?\n\n` +
      `This downloads ${offer.size_gb} GB over your internet connection and stores it on this computer.`)) {
      this.pull(offer.name, offer.size_gb);
    }
  }

  private pull(name: string, totalGb: number | null): void {
    if (this.download && !this.download.error) return;  // one at a time
    this.download = { name, totalGb, doneGb: 0, status: 'Starting…', error: null };
    const layers = new Map<string, number>();  // Ollama reports progress per layer
    this.eventSource = new EventSource(this.curedService.ollamaPullStreamUrl(name));
    this.eventSource.onmessage = (event) => this.zone.run(() => {
      const data = JSON.parse(event.data);
      if (data.status === 'error') {
        this.finish(data.error || 'Download failed');
        return;
      }
      if (data.total && data.completed !== undefined) {
        layers.set(data.status, data.completed);
        this.download!.doneGb = [...layers.values()].reduce((a, b) => a + b, 0) / 1e9;
      }
      this.download!.status = data.status || '';
      if (data.status === 'success') {
        this.finish(null);
        this.load(false);
        this.picked.emit(name);
      }
    });
    this.eventSource.onerror = () => this.zone.run(() => {
      if (this.download && this.download.status !== 'success') {
        this.finish('The connection to the download was lost');
      }
    });
  }

  private finish(error: string | null): void {
    this.eventSource?.close();
    this.eventSource = null;
    if (error) {
      this.download!.error = error;
    } else {
      this.download = null;
    }
  }

  /** Stop following the download (Ollama finishes or drops it on its own). */
  dismissDownload(): void {
    this.eventSource?.close();
    this.eventSource = null;
    this.download = null;
  }

  get downloadPercent(): number {
    const d = this.download;
    return d && d.totalGb ? Math.min(100, Math.round(d.doneGb / d.totalGb * 100)) : 0;
  }

  /** A few words for the list; the full reason is in the tooltip. */
  shortReason(reason: string): string {
    if (/retired/i.test(reason)) return 'retired';
    if (/not found/i.test(reason)) return 'not found';
    return reason.length > 40 ? 'unavailable' : reason;
  }
}

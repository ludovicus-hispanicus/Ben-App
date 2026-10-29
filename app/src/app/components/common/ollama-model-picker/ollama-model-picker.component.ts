import { Component, EventEmitter, Output } from '@angular/core';
import { CuredService, OllamaVisionModel } from 'src/app/services/cured.service';

/**
 * Dropdown of the models installed in Ollama. The list is fetched from Ollama the
 * first time the dropdown is opened (and again on "Refresh"), so newly pulled
 * models show up without reloading the page. Models that can't read images, or
 * that Ollama can't run, are listed greyed out with the reason.
 */
@Component({
  selector: 'app-ollama-model-picker',
  templateUrl: './ollama-model-picker.component.html',
  styleUrls: ['./ollama-model-picker.component.scss']
})
export class OllamaModelPickerComponent {
  /** The exact Ollama name of the chosen model, e.g. "qwen3-vl:4b". */
  @Output() picked = new EventEmitter<string>();

  loaded = false;
  loading = false;
  ollamaAvailable = true;
  usable: OllamaVisionModel[] = [];
  notUsable: Array<{ name: string; reason: string }> = [];

  constructor(private curedService: CuredService) {}

  onOpenedChange(open: boolean): void {
    if (open && !this.loaded && !this.loading) {
      this.load();
    }
  }

  load(): void {
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
      },
      error: () => {
        this.ollamaAvailable = false;
        this.loaded = true;
        this.loading = false;
      }
    });
  }

  onSelect(value: string | null): void {
    if (value === RELOAD) {
      this.load();
    } else if (value) {
      this.picked.emit(value);
    }
  }

  /** A few words for the list; the full reason is in the tooltip. */
  shortReason(reason: string): string {
    if (/retired/i.test(reason)) return 'retired';
    if (/not found/i.test(reason)) return 'not found';
    return reason.length > 40 ? 'unavailable' : reason;
  }

  readonly RELOAD = RELOAD;
}

const RELOAD = '__reload__';

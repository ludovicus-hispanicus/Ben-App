import { Component, OnInit, OnDestroy, NgZone, ChangeDetectorRef } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Subscription } from 'rxjs';
import { environment } from 'src/environments/environment';
import { ReplacementMappingsService, ReplacementMapping } from 'src/app/services/replacement-mappings.service';

interface OcrPrompt {
  key: string;
  value: string;
  editing?: boolean;
  editValue?: string;
}

interface RecommendedModel {
  id: string;
  name: string;
  description: string;
  size_gb: number;
  vram_gb: number;
  installed: boolean;
}

interface KrakenModel {
  name: string;
  path: string;
  size_mb: number;
  created: string;
}

@Component({
  selector: 'app-settings',
  templateUrl: './settings.component.html',
  styleUrls: ['./settings.component.scss']
})
export class SettingsComponent implements OnInit, OnDestroy {

  // Placeholder settings - to be implemented
  settings = {
    defaultOcrModel: 'kraken',
    useGpu: false,
    ollamaUrl: 'http://localhost:11434',
    autoSave: true
  };

  // OCR model categories - dynamically updated based on installed models
  ocrModelGroups: { label: string; models: { value: string; label: string }[] }[] = [];

  // Base models that are always available
  private baseModels = {
    kraken: [
      { value: 'kraken', label: 'Kraken (CPU)' }
    ],
    local: [
      { value: 'nemotron_local', label: 'Nemotron Parse (8GB GPU)' }
    ],
    ollamaCloud: [
      { value: 'qwen3_vl_235b_cloud', label: 'Qwen3 VL 235B Cloud' },
      { value: 'qwen3_vl_235b_thinking', label: 'Qwen3 VL 235B Thinking' }
    ],
    api: [
      { value: 'openai_gpt4o', label: 'GPT-4o (OpenAI)' },
      { value: 'anthropic_claude', label: 'Claude 3.5 Sonnet (Anthropic)' }
    ]
  };

  // OCR Prompts
  ocrPrompts: OcrPrompt[] = [];
  loadingPrompts = false;
  promptsError: string | null = null;
  defaultPrompt: string = 'dictionary';  // Default prompt for OCR

  // Available Ollama models
  availableOllamaModels: string[] = [];
  loadingModels = false;
  ollamaStatus: 'checking' | 'available' | 'unavailable' = 'checking';

  // Recommended models for download
  recommendedModels: RecommendedModel[] = [];
  loadingRecommended = false;
  downloadingModel: string | null = null;
  downloadProgress: { status: string; percent: number } | null = null;

  // GPU status
  gpuStatus: {
    cuda_available: boolean;
    gpu_name: string | null;
    gpu_memory_gb: number | null;
    models: {
      [key: string]: {
        available: boolean;
        loaded: boolean;
        requires_preload: boolean;
        vram_required_gb: number;
      }
    }
  } | null = null;
  loadingGpuStatus = false;
  preloadingModel: string | null = null;

  // Replacement mappings (Utilities tab)
  mappingCategories: string[] = [];
  newMappingFrom: string = '';
  newMappingTo: string = '';
  newMappingCategory: string = 'Custom';
  private mappingsSubscription: Subscription;

  // Kraken Models
  krakenModels: KrakenModel[] = [];
  loadingKrakenModels = false;
  activeKrakenModel: { name: string; is_pretrained: boolean; size_mb: number; last_modified: string | null } | null = null;
  activatingModel: string | null = null;
  deletingModel: string | null = null;

  constructor(
    private http: HttpClient,
    private mappingsService: ReplacementMappingsService,
    private ngZone: NgZone,
    private cdr: ChangeDetectorRef
  ) { }

  ngOnInit(): void {
    // Initialize model groups with base models
    this.buildOcrModelGroups();

    this.loadPrompts();
    this.loadOllamaModels();  // This will update groups with installed Ollama models
    this.checkOllamaStatus();
    this.loadDefaultPrompt();
    this.loadGpuStatus();
    this.loadRecommendedModels();
    this.loadKrakenModels();

    // Subscribe to mappings changes
    this.mappingsSubscription = this.mappingsService.mappings$.subscribe(() => {
      this.mappingCategories = this.mappingsService.getCategories();
    });
  }

  ngOnDestroy(): void {
    if (this.mappingsSubscription) {
      this.mappingsSubscription.unsubscribe();
    }
  }

  loadGpuStatus(): void {
    this.loadingGpuStatus = true;
    this.http.get<any>(`${environment.apiUrl}/cured/gpu/status`)
      .subscribe({
        next: (status) => {
          this.gpuStatus = status;
          this.loadingGpuStatus = false;
        },
        error: () => {
          this.gpuStatus = null;
          this.loadingGpuStatus = false;
        }
      });
  }

  preloadModel(modelName: string): void {
    this.preloadingModel = modelName;
    this.http.post<any>(`${environment.apiUrl}/cured/gpu/preload/${modelName}`, {})
      .subscribe({
        next: () => {
          this.preloadingModel = null;
          // Refresh GPU status to show loaded state
          this.loadGpuStatus();
        },
        error: (error) => {
          this.preloadingModel = null;
          console.error('Failed to preload model:', error);
          alert('Failed to preload model: ' + (error.error?.detail || error.message));
        }
      });
  }

  unloadModel(modelName: string): void {
    this.preloadingModel = modelName;  // Reuse for loading state
    this.http.post<any>(`${environment.apiUrl}/cured/gpu/unload/${modelName}`, {})
      .subscribe({
        next: () => {
          this.preloadingModel = null;
          // Refresh GPU status to show unloaded state
          this.loadGpuStatus();
        },
        error: (error) => {
          this.preloadingModel = null;
          console.error('Failed to unload model:', error);
          alert('Failed to unload model: ' + (error.error?.detail || error.message));
        }
      });
  }

  loadDefaultPrompt(): void {
    this.http.get<{ default_prompt: string }>(`${environment.apiUrl}/cured/ollama/default-prompt`)
      .subscribe({
        next: (response) => {
          this.defaultPrompt = response.default_prompt;
        },
        error: () => {
          // Keep default value if endpoint fails
        }
      });
  }

  saveDefaultPrompt(): void {
    this.http.put<any>(`${environment.apiUrl}/cured/ollama/default-prompt`, {
      prompt_key: this.defaultPrompt
    }).subscribe({
      next: () => {
        console.log('Default prompt saved:', this.defaultPrompt);
      },
      error: (error) => {
        console.error('Failed to save default prompt:', error);
      }
    });
  }

  loadPrompts(): void {
    this.loadingPrompts = true;
    this.promptsError = null;

    this.http.get<{ prompts: OcrPrompt[] }>(`${environment.apiUrl}/cured/ollama/prompts`)
      .subscribe({
        next: (response) => {
          this.ocrPrompts = response.prompts.map(p => ({
            ...p,
            editing: false,
            editValue: p.value
          }));
          this.loadingPrompts = false;
        },
        error: (error) => {
          this.promptsError = 'Failed to load prompts';
          this.loadingPrompts = false;
          console.error('Failed to load prompts:', error);
        }
      });
  }

  loadOllamaModels(): void {
    this.loadingModels = true;
    this.http.get<string[]>(`${environment.apiUrl}/cured/ollama/models`)
      .subscribe({
        next: (models) => {
          this.availableOllamaModels = models;
          this.loadingModels = false;
          this.buildOcrModelGroups();
        },
        error: () => {
          this.availableOllamaModels = [];
          this.loadingModels = false;
          this.buildOcrModelGroups();
        }
      });
  }

  /**
   * Build the OCR model groups based on installed Ollama models
   */
  private buildOcrModelGroups(): void {
    // Map Ollama model names to friendly labels
    const ollamaModelLabels: { [key: string]: string } = {
      'deepseek-ocr': 'DeepSeek OCR',
      'deepseek-ocr:latest': 'DeepSeek OCR',
      'qwen3-vl:4b': 'Qwen3 VL 4B',
      'qwen3-vl:8b': 'Qwen3 VL 8B',
      'qwen3-vl:32b': 'Qwen3 VL 32B',
      'llama4:scout': 'Llama 4 Scout',
      'mistral-small3.1': 'Mistral Small 3.1',
      'llava:34b': 'LLaVA 34B'
    };

    // Build local models from installed Ollama models (excluding cloud models)
    const localOllamaModels = this.availableOllamaModels
      .filter(name => !name.toLowerCase().includes('cloud'))
      .map(name => ({
        value: `ollama_${name.replace(/[:\-\.]/g, '_')}`,
        label: ollamaModelLabels[name] || name
      }));

    // Combine base local models with installed Ollama local models
    const localModels = [
      ...this.baseModels.local,
      ...localOllamaModels
    ];

    // Build groups
    this.ocrModelGroups = [
      { label: 'CPU', models: this.baseModels.kraken },
      { label: 'Local GPU', models: localModels },
      { label: 'Ollama Cloud', models: this.baseModels.ollamaCloud },
      { label: 'API', models: this.baseModels.api }
    ];
  }

  checkOllamaStatus(): void {
    this.ollamaStatus = 'checking';
    this.http.get<string[]>(`${environment.apiUrl}/cured/ollama/models`)
      .subscribe({
        next: () => {
          this.ollamaStatus = 'available';
        },
        error: () => {
          this.ollamaStatus = 'unavailable';
        }
      });
  }

  loadRecommendedModels(): void {
    this.loadingRecommended = true;
    this.http.get<{ ollama_available: boolean; models: RecommendedModel[] }>(
      `${environment.apiUrl}/cured/ollama/recommended-models`
    ).subscribe({
      next: (response) => {
        this.recommendedModels = response.models;
        this.loadingRecommended = false;
      },
      error: () => {
        this.recommendedModels = [];
        this.loadingRecommended = false;
      }
    });
  }

  downloadModel(modelId: string): void {
    if (this.downloadingModel) return;

    this.downloadingModel = modelId;
    this.downloadProgress = { status: 'Starting download...', percent: 0 };

    // Use Server-Sent Events for streaming progress
    const eventSource = new EventSource(
      `${environment.apiUrl}/cured/ollama/pull/${encodeURIComponent(modelId)}/stream`
    );

    eventSource.onmessage = (event) => {
      // Run inside Angular zone to trigger change detection
      this.ngZone.run(() => {
        try {
          const data = JSON.parse(event.data);
          this.downloadProgress = {
            status: data.status || 'Downloading...',
            percent: data.percent || 0
          };
          this.cdr.detectChanges();

          // Check for completion or error
          if (data.status === 'success' || data.percent === 100) {
            eventSource.close();
            this.downloadingModel = null;
            this.downloadProgress = null;
            // Refresh models list
            this.loadOllamaModels();
            this.loadRecommendedModels();
          } else if (data.status === 'error') {
            eventSource.close();
            this.downloadingModel = null;
            this.downloadProgress = null;
            alert('Download failed: ' + (data.error || 'Unknown error'));
          }
        } catch (e) {
          console.error('Failed to parse progress:', e);
        }
      });
    };

    eventSource.onerror = () => {
      this.ngZone.run(() => {
        eventSource.close();
        // Check if model was actually installed despite connection close
        this.loadRecommendedModels();
        this.downloadingModel = null;
        this.downloadProgress = null;
        this.cdr.detectChanges();
      });
    };
  }

  cancelDownload(): void {
    // Note: Ollama doesn't support canceling downloads directly
    // This just resets the UI state
    this.downloadingModel = null;
    this.downloadProgress = null;
  }

  canRunOnGpu(model: { vram_gb: number }): boolean {
    if (!this.gpuStatus?.cuda_available) return false;
    return (this.gpuStatus.gpu_memory_gb || 0) >= model.vram_gb;
  }

  startEditing(prompt: OcrPrompt): void {
    prompt.editing = true;
    prompt.editValue = prompt.value;
  }

  cancelEditing(prompt: OcrPrompt): void {
    prompt.editing = false;
    prompt.editValue = prompt.value;
  }

  savePrompt(prompt: OcrPrompt): void {
    if (!prompt.editValue) return;

    this.http.put<any>(`${environment.apiUrl}/cured/ollama/prompts/${prompt.key}`, {
      value: prompt.editValue
    }).subscribe({
      next: () => {
        prompt.value = prompt.editValue!;
        prompt.editing = false;
      },
      error: (error) => {
        console.error('Failed to save prompt:', error);
        alert('Failed to save prompt');
      }
    });
  }

  getPromptLabel(key: string): string {
    const labels: { [key: string]: string } = {
      'plain': 'Plain Text',
      'markdown': 'Markdown',
      'dictionary': 'Akkadian Dictionary'
    };
    return labels[key] || key;
  }

  getPromptDescription(key: string): string {
    const descriptions: { [key: string]: string } = {
      'plain': 'Simple OCR output without formatting',
      'markdown': 'OCR with basic markdown formatting',
      'dictionary': 'Specialized prompt for Akkadian dictionary entries with bold/italic detection'
    };
    return descriptions[key] || '';
  }

  saveSettings(): void {
    // TODO: Save settings to backend/localStorage
    console.log('Settings saved:', this.settings);
  }

  // --- Replacement Mappings (Utilities tab) ---

  getMappingsByCategory(category: string): ReplacementMapping[] {
    return this.mappingsService.getMappingsByCategory(category);
  }

  allCategoryEnabled(category: string): boolean {
    const mappings = this.getMappingsByCategory(category);
    return mappings.length > 0 && mappings.every(m => m.enabled);
  }

  toggleMapping(mapping: ReplacementMapping): void {
    this.mappingsService.toggleMapping(mapping);
  }

  toggleCategoryMappings(category: string): void {
    this.mappingsService.toggleCategoryMappings(category);
  }

  addMapping(): void {
    if (!this.newMappingFrom) return;
    this.mappingsService.addMapping(this.newMappingFrom, this.newMappingTo, this.newMappingCategory);
    this.newMappingFrom = '';
    this.newMappingTo = '';
  }

  removeMapping(mapping: ReplacementMapping): void {
    this.mappingsService.removeMapping(mapping);
  }

  resetMappings(): void {
    this.mappingsService.resetToDefaults();
  }

  // --- Kraken Model Management ---

  loadKrakenModels(): void {
    this.loadingKrakenModels = true;

    // Load models and active model in parallel
    this.http.get<{ models: KrakenModel[] }>(`${environment.apiUrl}/cured/training/kraken/models`)
      .subscribe({
        next: (response) => {
          this.krakenModels = response.models;
          this.loadingKrakenModels = false;
        },
        error: () => {
          this.krakenModels = [];
          this.loadingKrakenModels = false;
        }
      });

    this.http.get<any>(`${environment.apiUrl}/cured/training/kraken/active-model`)
      .subscribe({
        next: (response) => {
          this.activeKrakenModel = response;
        },
        error: () => {
          this.activeKrakenModel = null;
        }
      });
  }

  activateKrakenModel(modelName: string): void {
    if (this.activatingModel) return;

    this.activatingModel = modelName;
    this.http.post<any>(`${environment.apiUrl}/cured/training/kraken/models/${encodeURIComponent(modelName)}/activate`, {})
      .subscribe({
        next: () => {
          this.activatingModel = null;
          this.loadKrakenModels();  // Refresh to show new active model
        },
        error: (error) => {
          this.activatingModel = null;
          console.error('Failed to activate model:', error);
          alert('Failed to activate model: ' + (error.error?.detail || error.message));
        }
      });
  }

  deleteKrakenModel(modelName: string): void {
    if (this.deletingModel) return;

    if (!confirm(`Are you sure you want to delete the model "${modelName}"? This cannot be undone.`)) {
      return;
    }

    this.deletingModel = modelName;
    this.http.delete<any>(`${environment.apiUrl}/cured/training/kraken/models/${encodeURIComponent(modelName)}`)
      .subscribe({
        next: () => {
          this.deletingModel = null;
          this.loadKrakenModels();  // Refresh the list
        },
        error: (error) => {
          this.deletingModel = null;
          console.error('Failed to delete model:', error);
          alert('Failed to delete model: ' + (error.error?.detail || error.message));
        }
      });
  }

  isProtectedModel(modelName: string): boolean {
    const protectedNames = ['model', 'base'];
    return protectedNames.includes(modelName.toLowerCase());
  }

  formatDate(isoDate: string): string {
    if (!isoDate) return 'Unknown';
    const date = new Date(isoDate);
    return date.toLocaleDateString() + ' ' + date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }

}

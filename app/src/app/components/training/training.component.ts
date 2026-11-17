import { Component, OnInit, OnDestroy, ChangeDetectorRef, ViewChild, ElementRef, AfterViewChecked } from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';
import { Subject, interval } from 'rxjs';
import { takeUntil, switchMap, take } from 'rxjs/operators';

import { CuredService, TrainedModel, ActiveModelInfo } from '../../services/cured.service';
import { YoloTrainingService } from '../../services/yolo-training.service';
import { NotificationService } from '../../services/notification.service';
import { DatasetService } from '../../services/dataset.service';
import { ModuleService } from '../../services/module.service';
import { ToolbarService } from '../../services/toolbar.service';
import { DatasetPreview } from '../../models/cured';
import {
  DatasetListItem,
  DatasetStats,
  ModelInfo,
  TrainingConfig,
  TrainingProgress as YoloTrainingProgress,
  TrainingStatus as YoloTrainingStatus,
  TrainingJob,
  DEFAULT_TRAINING_CONFIG,
  YoloHealthResponse,
  YoloClass,
  CLASS_COLORS
} from '../../models/yolo-training';

export enum TrainingTab {
  CuReD = 'cured',
  YOLO = 'yolo'
}

export enum TrainingEngine {
  Kraken = 'kraken',
  DeepSeek = 'deepseek'
}

export enum OcrViewMode {
  Datasets = 'datasets',
  Models = 'models',
  Training = 'training',
  Batch = 'batch',
  Layout = 'layout',
  Export = 'export'
}

export enum YoloViewMode {
  Dashboard = 'dashboard',
  Datasets = 'datasets',
  Models = 'models',
  Training = 'training',
  Annotate = 'annotate'
}

interface TrainingStatus {
  curatedTexts: number;
  previousLines: number;
  newLines: number;
  totalLines: number;
  requiredForNextTraining: number;
  progress: number;
  isReady: boolean;
  lastTraining: string | null;
  currentTraining: any | null;
}

interface OcrModel {
  value: string;
  label: string;
}

@Component({
  selector: 'app-training',
  templateUrl: './training.component.html',
  styleUrls: ['./training.component.scss']
})
export class TrainingComponent implements OnInit, OnDestroy, AfterViewChecked {
  private destroy$ = new Subject<void>();

  @ViewChild('krakenLogTerminal') krakenLogTerminal: ElementRef;
  private shouldScrollLogs = true;

  // OCR View Mode (Datasets / Models / Training / Batch / Layout / Export)
  private _ocrViewMode: OcrViewMode = OcrViewMode.Datasets;
  get ocrViewMode(): OcrViewMode {
    return this._ocrViewMode;
  }
  set ocrViewMode(mode: OcrViewMode) {
    this._ocrViewMode = mode;
    // After the view has changed: the page view (<cured>) clears the toolbar when it goes
    setTimeout(() => this.applyViewNavigation());
  }
  OcrViewMode = OcrViewMode;

  // CuReD stage (0=dashboard, 1=pdf, 2+=visualizer)
  curedStage = 0;
  // Production view mode ('dashboard' or 'editor')
  productionViewMode: string = 'dashboard';

  onCuredStageChange(stage: number): void {
    this.curedStage = stage;
    this.cdr.detectChanges();
  }

  get hideChrome(): boolean {
    return (this.curedStage >= 2 && this.ocrViewMode === OcrViewMode.Datasets)
        || (this.ocrViewMode === OcrViewMode.Export && this.productionViewMode === 'editor');
  }

  // Tab state (legacy)
  activeTab: TrainingTab = TrainingTab.CuReD;
  TrainingTab = TrainingTab;

  // Dataset selector for training (multi-select)
  trainingDatasets: DatasetPreview[] = [];
  selectedTrainingDatasetIds: number[] = [];

  // ========== CuReD OCR Training ==========
  trainingStatus: TrainingStatus = {
    curatedTexts: 0,
    previousLines: 0,
    newLines: 0,
    totalLines: 0,
    requiredForNextTraining: 1000,
    progress: 0,
    isReady: false,
    lastTraining: null,
    currentTraining: null
  };

  availableOcrModels: OcrModel[] = [];
  krakenBaseModels: { id: string; name: string; description: string }[] = [];
  selectedBaseModel = 'from_scratch';
  trainingModelName = '';
  isOcrTraining = false;
  ocrTrainingProgress: any = null;
  epochHistory: any[] = [];

  // Kraken training config
  krakenEpochs = 500;
  krakenBatchSize = 1;
  krakenPatience = 10;
  krakenDevice = 'auto';

  // Base model metadata (from training service)
  baseModelsMetadata: { [key: string]: any } = {};

  // Training engine toggle
  trainingEngine: TrainingEngine = TrainingEngine.Kraken;
  TrainingEngine = TrainingEngine;

  // Training right panel tabs
  trainingRightTab: 'progress' | 'jobs' = 'jobs';

  // ========== OCR Models ==========
  krakenModels: TrainedModel[] = [];
  krakenActiveModel: ActiveModelInfo | null = null;
  selectedKrakenModel: TrainedModel | null = null;
  // ========== DeepSeek-OCR LoRA Training (result: an Ollama model) ==========
  deepseekTrainingStatus: TrainingStatus & { available?: boolean; unavailableReason?: string | null } = {
    curatedTexts: 0,
    previousLines: 0,
    newLines: 0,
    totalLines: 0,
    requiredForNextTraining: 30,
    progress: 0,
    isReady: false,
    lastTraining: null,
    currentTraining: null,
    available: false,
    unavailableReason: null
  };
  deepseekModels: TrainedModel[] = [];
  selectedDeepSeekModel: TrainedModel | null = null;
  deepseekModelName = '';
  deepseekEpochs = 2;
  deepseekPatience = 2;
  deepseekDevice = 'auto';
  isDeepSeekTraining = false;
  deepseekTrainingProgress: any = null;
  deepseekEpochHistory: any[] = [];

  // Optional modules (set once the module state has loaded)
  yoloEnabled = false;

  // ========== YOLO Training ==========
  yoloViewMode: YoloViewMode = YoloViewMode.Dashboard;
  YoloViewMode = YoloViewMode;
  isYoloLoading = false;
  yoloHealthStatus: YoloHealthResponse | null = null;

  // Datasets
  datasets: DatasetListItem[] = [];
  selectedDataset: DatasetStats | null = null;

  // Models
  yoloModels: ModelInfo[] = [];
  yoloBaseModels: string[] = [];
  selectedYoloModel: ModelInfo | null = null;

  // Training
  yoloTrainingConfig: TrainingConfig = { ...DEFAULT_TRAINING_CONFIG };
  activeTrainingJobs: TrainingJob[] = [];
  currentYoloTrainingProgress: YoloTrainingProgress | null = null;
  private yoloTrainingEventSource: EventSource | null = null;

  // New dataset form
  newDatasetName = '';
  newDatasetClasses: string[] = ['entry', 'subentry', 'guidewords'];
  newDatasetDescription = '';

  // Training form
  yoloTrainingDatasetName = '';
  yoloTrainingBaseModel = 'yolo26s.pt';
  yoloTrainingOutputName = '';

  // Annotation state
  annotationDataset = '';
  annotationClasses: YoloClass[] = [];

  // Class colors
  classColors = CLASS_COLORS;

  constructor(
    private curedService: CuredService,
    private yoloService: YoloTrainingService,
    private notification: NotificationService,
    private datasetService: DatasetService,
    private cdr: ChangeDetectorRef,
    private route: ActivatedRoute,
    private router: Router,
    private toolbarService: ToolbarService,
    private moduleService: ModuleService
  ) {}

  private static readonly VIEW_LABELS: { [mode: string]: string } = {
    models: 'Models', training: 'Training', batch: 'Batch', layout: 'Layout', export: 'Export',
  };

  /** Path in the toolbar for the hub's tabs (the page view sets its own: datasets, texts). */
  private applyViewNavigation(): void {
    const label = TrainingComponent.VIEW_LABELS[this._ocrViewMode];
    if (!label) {
      return;
    }
    const home = { label: 'CuReD', action: () => this.goToCuredStart() };
    this.toolbarService.setNavigation(home, [home, { label }]);
  }

  /** Back to the CuReD start page: the page view with the list of datasets. */
  goToCuredStart(): void {
    if (this._ocrViewMode !== OcrViewMode.Datasets) {
      this.ocrViewMode = OcrViewMode.Datasets;
    }
    // Drop a tab's leftover URL (e.g. ?view=layout), so a reload stays on the start page
    if (this.router.url !== '/cured') {
      this.router.navigate(['/cured']);
    }
  }

  onProductionViewModeChange(mode: string): void {
    setTimeout(() => {
      this.productionViewMode = mode;
      this.cdr.detectChanges();
    });
  }

  ngOnInit(): void {
    this.toolbarService.curedHome$.pipe(takeUntil(this.destroy$)).subscribe(() => {
      if (this._ocrViewMode !== OcrViewMode.Datasets) {
        this.ocrViewMode = OcrViewMode.Datasets;
      }
    });
    this.loadTrainingDatasets();
    this.loadOcrTrainingStatus();
    this.loadAvailableModels();
    this.loadKrakenBaseModels();

    // Layout is an optional module: only call it when installed and switched on
    this.moduleService.enabledModules$.pipe(take(1), takeUntil(this.destroy$)).subscribe(modules => {
      this.yoloEnabled = modules['yolo'] !== false;
      this.loadDeepSeekTrainingStatus();
      this.loadOcrModels();
      this.checkYoloHealth();
      this.loadYoloDashboardData();

      // Poll for training status updates
      this.startTrainingStatusPolling();
    });

    // Switch the embedded view based on URL hints from cross-component navigation:
    // - linkedIdentifier (production "Add linked page") → switch to Datasets so <cured> renders
    // - view=production (cured Finish button) → switch back to Export so <app-production> renders
    this.route.queryParams.pipe(takeUntil(this.destroy$)).subscribe(params => {
      if ((params['linkedIdentifier'] || (params['library_project'] && !params['view']))
          && this.ocrViewMode !== OcrViewMode.Datasets) {
        // Linked page from production, or "Open in CuReD" from the Library: <cured> loads it
        this.ocrViewMode = OcrViewMode.Datasets;
      } else if (params['view'] === 'production' && this.ocrViewMode !== OcrViewMode.Export) {
        this.ocrViewMode = OcrViewMode.Export;
      } else if (params['view'] === 'layout' && this.ocrViewMode !== OcrViewMode.Layout) {
        // Layout (e.g. "Open in Layout" from the Library, which also passes the page)
        this.ocrViewMode = OcrViewMode.Layout;
      } else if (params['view'] === 'batch' || params['view'] === 'training') {
        // Entry points on the dashboard
        this.setOcrViewMode(params['view'] === 'batch' ? OcrViewMode.Batch : OcrViewMode.Training);
      }
    });
  }

  ngAfterViewChecked(): void {
    this.scrollLogTerminal();
  }

  private scrollLogTerminal(): void {
    if (this.shouldScrollLogs && this.krakenLogTerminal) {
      const el = this.krakenLogTerminal.nativeElement;
      el.scrollTop = el.scrollHeight;
    }
  }

  ngOnDestroy(): void {
    this.destroy$.next();
    this.destroy$.complete();
    this.closeYoloTrainingStream();
  }

  setOcrViewMode(mode: OcrViewMode): void {
    this.ocrViewMode = mode;
    if (mode === OcrViewMode.Models) {
      this.loadOcrModels();
    } else if (mode === OcrViewMode.Training) {
      this.loadOcrTrainingStatus();
      this.loadDeepSeekTrainingStatus();
    }
  }

  // ========== OCR Models Methods ==========

  loadOcrModels(): void {
    this.curedService.listKrakenModels().subscribe({
      next: (response) => {
        this.krakenModels = response.models;
      },
      error: (err) => console.error('Failed to load Kraken models', err)
    });

    this.curedService.getKrakenActiveModel().subscribe({
      next: (model) => {
        this.krakenActiveModel = model;
      },
      error: (err) => console.error('Failed to load Kraken active model', err)
    });

    this.curedService.listDeepSeekModels().subscribe({
      next: (response) => {
        this.deepseekModels = response.models;
      },
      error: (err) => console.error('Failed to load DeepSeek models', err)
    });
  }

  activateKrakenModel(modelName: string): void {
    this.curedService.activateKrakenModel(modelName).subscribe({
      next: () => {
        this.notification.showSuccess(`Kraken model "${modelName}" activated`);
        this.loadOcrModels();
      },
      error: (err) => this.notification.showError('Failed to activate model')
    });
  }

  deleteKrakenModel(modelName: string): void {
    if (!confirm(`Are you sure you want to delete Kraken model "${modelName}"?`)) {
      return;
    }
    this.curedService.deleteKrakenModel(modelName).subscribe({
      next: () => {
        this.notification.showSuccess(`Model "${modelName}" deleted`);
        this.selectedKrakenModel = null;
        this.loadOcrModels();
      },
      error: (err) => this.notification.showError(err?.error?.detail || 'Failed to delete model')
    });
  }

  deleteDeepSeekModel(model: TrainedModel): void {
    const what = model.ollama_model
      ? `DeepSeek model "${model.name}" and its Ollama model "${model.ollama_model}"`
      : `DeepSeek model "${model.name}"`;
    if (!confirm(`Delete ${what}?`)) {
      return;
    }
    this.curedService.deleteDeepSeekModel(model.name).subscribe({
      next: () => {
        this.notification.showSuccess(`Model "${model.name}" deleted`);
        this.selectedDeepSeekModel = null;
        this.loadOcrModels();
      },
      error: (err) => this.notification.showError(err?.error?.detail || 'Failed to delete model')
    });
  }

  selectModel(kind: 'kraken' | 'deepseek', model: TrainedModel): void {
    this.selectedKrakenModel = kind === 'kraken' ? model : null;
    this.selectedDeepSeekModel = kind === 'deepseek' ? model : null;
  }

  getTrainingStatusColor(status: string): string {
    switch (status) {
      case 'completed': return '#4caf50';
      case 'training': case 'preparing': case 'evaluating': return '#1976d2';
      case 'failed': return '#f44336';
      case 'cancelled': return '#ff9800';
      default: return '#666';
    }
  }

  // ========== Dataset Selection ==========

  loadTrainingDatasets(): void {
    this.datasetService.list().subscribe({
      next: (datasets) => {
        this.trainingDatasets = datasets || [];
      },
      error: () => {}
    });
  }

  onTrainingDatasetChange(): void {
    this.loadOcrTrainingStatus();
    this.loadDeepSeekTrainingStatus();
  }

  addTrainingDataset(datasetId: number): void {
    if (datasetId && !this.selectedTrainingDatasetIds.includes(datasetId)) {
      this.selectedTrainingDatasetIds = [...this.selectedTrainingDatasetIds, datasetId];
      this.onTrainingDatasetChange();
    }
  }

  removeTrainingDataset(datasetId: number): void {
    this.selectedTrainingDatasetIds = this.selectedTrainingDatasetIds.filter(id => id !== datasetId);
    this.onTrainingDatasetChange();
  }

  getAvailableTrainingDatasets(): any[] {
    return this.trainingDatasets.filter(p => !this.selectedTrainingDatasetIds.includes(p.dataset_id));
  }

  getDatasetName(datasetId: number): string {
    const dataset = this.trainingDatasets.find(p => p.dataset_id === datasetId);
    return dataset ? dataset.name : `Dataset ${datasetId}`;
  }

  // ========== CuReD OCR Training Methods ==========

  loadOcrTrainingStatus(): void {
    const pids = this.selectedTrainingDatasetIds.length > 0 ? this.selectedTrainingDatasetIds : undefined;
    this.curedService.getKrakenTrainingStatus(pids).subscribe({
      next: (status) => {
        this.trainingStatus = status;
        if (status.currentTraining) {
          this.ocrTrainingProgress = status.currentTraining;
          this.isOcrTraining = status.currentTraining.status === 'training' ||
                               status.currentTraining.status === 'preparing';
          if (status.currentTraining.epoch_history) {
            this.epochHistory = status.currentTraining.epoch_history;
          }
        }
      },
      error: (err) => {
        console.error('Failed to load training status', err);
      }
    });
  }

  loadAvailableModels(): void {
    this.curedService.getAvailableOcrModels().subscribe({
      next: (response) => {
        this.availableOcrModels = response.models;
      },
      error: (err) => {
        console.error('Failed to load available models', err);
      }
    });
  }

  loadKrakenBaseModels(): void {
    this.curedService.getKrakenBaseModels().subscribe({
      next: (response) => {
        this.krakenBaseModels = response.models;
      },
      error: (err) => {
        console.error('Failed to load Kraken base models', err);
      }
    });
  }

  private krakenPollStop$ = new Subject<void>();
  private deepseekPollStop$ = new Subject<void>();

  startTrainingStatusPolling(): void {
    // Do a one-time check for each provider; only start polling if training is active
    this.curedService.getKrakenTrainingProgress().subscribe(p => this.handleKrakenProgress(p, true));
    this.curedService.getDeepSeekTrainingProgress().subscribe({
      next: p => this.handleDeepSeekProgress(p, true),
      error: () => {}
    });
  }

  startDeepSeekPolling(): void {
    this.deepseekPollStop$.next();
    interval(5000)
      .pipe(
        takeUntil(this.destroy$),
        takeUntil(this.deepseekPollStop$),
        switchMap(() => this.curedService.getDeepSeekTrainingProgress())
      )
      .subscribe({ next: (p) => this.handleDeepSeekProgress(p, false) });
  }

  private isRunning(status: string): boolean {
    return status === 'training' || status === 'preparing' || status === 'evaluating';
  }

  private handleDeepSeekProgress(progress: any, initialCheck: boolean): void {
    if (progress && progress.status !== 'idle') {
      this.deepseekTrainingProgress = progress;
      this.isDeepSeekTraining = this.isRunning(progress.status);
      if (progress.epoch_history) {
        this.deepseekEpochHistory = progress.epoch_history;
      }
      if (!this.isDeepSeekTraining) {
        this.deepseekPollStop$.next();
        this.loadDeepSeekTrainingStatus();
        if (progress.status === 'completed') {
          this.loadOcrModels();
        }
      } else if (initialCheck) {
        this.startDeepSeekPolling();
      }
    } else {
      this.isDeepSeekTraining = false;
    }
  }

  startKrakenPolling(): void {
    this.krakenPollStop$.next();
    interval(5000)
      .pipe(
        takeUntil(this.destroy$),
        takeUntil(this.krakenPollStop$),
        switchMap(() => this.curedService.getKrakenTrainingProgress())
      )
      .subscribe({ next: (p) => this.handleKrakenProgress(p, false) });
  }

  private handleKrakenProgress(progress: any, initialCheck: boolean): void {
    if (progress && progress.status !== 'idle') {
      this.ocrTrainingProgress = progress;
      this.isOcrTraining = progress.status === 'training' || progress.status === 'preparing';
      if (progress.epoch_history) {
        this.epochHistory = progress.epoch_history;
      }
      if (progress.status === 'completed' || progress.status === 'failed') {
        this.krakenPollStop$.next();
        this.loadOcrTrainingStatus();
      } else if (initialCheck) {
        this.startKrakenPolling();
      }
    } else {
      this.isOcrTraining = false;
    }
  }

  startOcrTraining(): void {
    if (!this.trainingModelName?.trim()) {
      this.notification.showWarning('Please enter a model name');
      return;
    }

    this.isOcrTraining = true;
    this.epochHistory = [];

    const baseModel = this.selectedBaseModel === 'from_scratch' ? null : this.selectedBaseModel;
    const pids = this.selectedTrainingDatasetIds.length > 0 ? this.selectedTrainingDatasetIds : undefined;
    this.curedService.startKrakenTraining(this.krakenEpochs, this.trainingModelName.trim(), baseModel, this.krakenBatchSize, this.krakenDevice, this.krakenPatience, pids).subscribe({
      next: (response) => {
        this.notification.showSuccess('Kraken training started');
        this.trainingRightTab = 'progress';
        this.startKrakenPolling();
        this.loadOcrTrainingStatus();
      },
      error: (err) => {
        this.notification.showError('Failed to start training: ' + (err.error?.detail || err.message));
        this.isOcrTraining = false;
      }
    });
  }

  cancelOcrTraining(): void {
    this.curedService.cancelKrakenTraining().subscribe({
      next: () => {
        this.notification.showSuccess('Training cancelled');
        this.isOcrTraining = false;
        this.loadOcrTrainingStatus();
      },
      error: (err) => {
        this.notification.showError('Failed to cancel training');
      }
    });
  }

  setTrainingEngine(engine: TrainingEngine): void {
    this.trainingEngine = engine;
    if (engine === TrainingEngine.DeepSeek) {
      this.loadDeepSeekTrainingStatus();
    } else {
      this.loadOcrTrainingStatus();
    }
  }

  // ========== Vision-model training helpers ==========

  /** Share of the whole run that is done, counting pages within the current epoch. */
  vlmProgressPercent(p: any): number {
    if (!p?.total_epochs) {
      return 0;
    }
    const withinEpoch = p.total_steps ? (p.step || 0) / p.total_steps : 0;
    const epochsDone = Math.max(0, (p.current_epoch || 0) - 1) + withinEpoch;
    return Math.min(100, (epochsDone / p.total_epochs) * 100);
  }

  formatEta(seconds: number): string {
    if (!seconds) {
      return '';
    }
    const h = Math.floor(seconds / 3600);
    const m = Math.round((seconds % 3600) / 60);
    return h > 0 ? `${h} h ${m} min` : `${m} min`;
  }

  // ========== DeepSeek-OCR Training Methods ==========

  loadDeepSeekTrainingStatus(): void {
    const pids = this.selectedTrainingDatasetIds.length > 0 ? this.selectedTrainingDatasetIds : undefined;
    this.curedService.getDeepSeekTrainingStatus(pids).subscribe({
      next: (status) => {
        this.deepseekTrainingStatus = status;
        if (status.currentTraining) {
          this.deepseekTrainingProgress = status.currentTraining;
          this.isDeepSeekTraining = this.isRunning(status.currentTraining.status);
          if (status.currentTraining.epoch_history) {
            this.deepseekEpochHistory = status.currentTraining.epoch_history;
          }
        }
      },
      error: (err) => console.error('Failed to load DeepSeek training status', err)
    });
  }

  /** Name the trained model gets in Ollama (same rule as the server). */
  /** Vision models trained outside BEn on Qwen3-VL (e.g. qwen3-vl-ahw) share the DeepSeek list. */
  isQwenModel(model: TrainedModel | null | undefined): boolean {
    return (model?.base_model || '').toLowerCase().startsWith('qwen');
  }

  deepseekOllamaName(name: string): string {
    const slug = (name || '').toLowerCase().replace(/[^a-z0-9._-]+/g, '-').replace(/^[-.]+|[-.]+$/g, '') || 'trained';
    return slug.startsWith('deepseek-ocr') ? slug : `deepseek-ocr-${slug}`;
  }

  startDeepSeekTraining(): void {
    if (!this.deepseekModelName?.trim()) {
      this.notification.showWarning('Please enter a model name');
      return;
    }
    this.isDeepSeekTraining = true;
    this.deepseekEpochHistory = [];
    const pids = this.selectedTrainingDatasetIds.length > 0 ? this.selectedTrainingDatasetIds : undefined;
    this.curedService.startDeepSeekTraining(
      this.deepseekEpochs, this.deepseekModelName.trim(), this.deepseekDevice, this.deepseekPatience, pids
    ).subscribe({
      next: (response) => {
        this.notification.showSuccess(`DeepSeek-OCR training started (Ollama model: ${response.ollama_model})`);
        this.trainingRightTab = 'progress';
        this.startDeepSeekPolling();
        this.loadDeepSeekTrainingStatus();
      },
      error: (err) => {
        this.notification.showError('Failed to start training: ' + (err.error?.detail || err.message));
        this.isDeepSeekTraining = false;
      }
    });
  }

  cancelDeepSeekTraining(): void {
    this.curedService.cancelDeepSeekTraining().subscribe({
      next: () => this.notification.showSuccess('Cancelling: the training stops after the current page'),
      error: (err) => this.notification.showError(err?.error?.detail || 'Failed to cancel training')
    });
  }

  // ========== YOLO Training Methods ==========

  checkYoloHealth(): void {
    if (!this.yoloEnabled) {
      return;
    }
    this.yoloService.checkHealth().subscribe({
      next: (response) => {
        this.yoloHealthStatus = response;
      },
      error: (err) => {
        this.yoloHealthStatus = { status: 'unhealthy', error: err.message };
      }
    });
  }

  loadYoloDashboardData(): void {
    if (!this.yoloEnabled) {
      return;
    }
    this.isYoloLoading = true;

    this.yoloService.listDatasets().subscribe({
      next: (datasets) => {
        this.datasets = datasets;
      },
      error: (err) => {
        this.notification.showError('Failed to load datasets');
      }
    });

    this.yoloService.listModels().subscribe({
      next: (response) => {
        this.yoloModels = response.models;
        this.yoloBaseModels = response.base_models;
        this.isYoloLoading = false;
      },
      error: (err) => {
        this.notification.showError('Failed to load models');
        this.isYoloLoading = false;
      }
    });

    this.loadYoloTrainingJobs();
  }

  loadYoloTrainingJobs(): void {
    this.yoloService.listTrainingJobs().subscribe({
      next: (jobs) => {
        this.activeTrainingJobs = jobs;
      },
      error: (err) => {
        console.error('Failed to load training jobs', err);
      }
    });
  }

  setYoloViewMode(mode: YoloViewMode): void {
    this.yoloViewMode = mode;
    if (mode === YoloViewMode.Dashboard) {
      this.loadYoloDashboardData();
    }
  }

  // Dataset management
  createDataset(): void {
    if (!this.newDatasetName.trim()) {
      this.notification.showWarning('Please enter a dataset name');
      return;
    }

    if (this.newDatasetClasses.length === 0) {
      this.notification.showWarning('Please add at least one class');
      return;
    }

    this.isYoloLoading = true;
    this.yoloService.createDataset({
      name: this.newDatasetName.trim(),
      classes: this.newDatasetClasses,
      description: this.newDatasetDescription
    }).subscribe({
      next: (response) => {
        if (response.success) {
          this.notification.showSuccess(`Dataset "${response.name}" created`);
          this.newDatasetName = '';
          this.newDatasetDescription = '';
          this.loadYoloDashboardData();
        } else {
          this.notification.showError(response.message);
        }
        this.isYoloLoading = false;
      },
      error: (err) => {
        this.notification.showError('Failed to create dataset');
        this.isYoloLoading = false;
      }
    });
  }

  selectDataset(dataset: DatasetListItem): void {
    this.isYoloLoading = true;
    this.yoloService.getDatasetStats(dataset.dataset_id).subscribe({
      next: (stats) => {
        this.selectedDataset = stats;
        this.isYoloLoading = false;
      },
      error: (err) => {
        this.notification.showError('Failed to load dataset details');
        this.isYoloLoading = false;
      }
    });
  }

  deleteDataset(datasetName: string): void {
    if (!confirm(`Are you sure you want to delete dataset "${datasetName}"?`)) {
      return;
    }

    this.yoloService.deleteDataset(datasetName).subscribe({
      next: (response) => {
        if (response.success) {
          this.notification.showSuccess(response.message);
          this.selectedDataset = null;
          this.loadYoloDashboardData();
        } else {
          this.notification.showError(response.message);
        }
      },
      error: (err) => {
        this.notification.showError('Failed to delete dataset');
      }
    });
  }

  addClass(): void {
    const className = prompt('Enter class name:');
    if (className && className.trim()) {
      if (!this.newDatasetClasses.includes(className.trim())) {
        this.newDatasetClasses.push(className.trim());
      }
    }
  }

  removeClass(index: number): void {
    this.newDatasetClasses.splice(index, 1);
  }

  openAnnotation(dataset: DatasetStats): void {
    this.annotationDataset = dataset.dataset_id;
    this.annotationClasses = dataset.classes;
    this.yoloViewMode = YoloViewMode.Annotate;
  }

  // Model management
  selectYoloModel(model: ModelInfo): void {
    this.selectedYoloModel = model;
  }

  deleteYoloModel(modelName: string): void {
    if (!confirm(`Are you sure you want to delete model "${modelName}"?`)) {
      return;
    }

    this.yoloService.deleteModel(modelName).subscribe({
      next: (response) => {
        if (response.success) {
          this.notification.showSuccess(response.message);
          this.selectedYoloModel = null;
          this.loadYoloDashboardData();
        } else {
          this.notification.showError(response.message);
        }
      },
      error: (err) => {
        this.notification.showError('Failed to delete model');
      }
    });
  }

  formatMetrics(metrics: any): string {
    if (!metrics) return 'N/A';
    const parts = [];
    if (metrics.mAP50) parts.push(`mAP50: ${(metrics.mAP50 * 100).toFixed(1)}%`);
    if (metrics['mAP50-95']) parts.push(`mAP50-95: ${(metrics['mAP50-95'] * 100).toFixed(1)}%`);
    return parts.join(', ') || 'N/A';
  }

  // YOLO Training
  startYoloTraining(): void {
    if (!this.yoloTrainingDatasetName) {
      this.notification.showWarning('Please select a dataset');
      return;
    }

    if (!this.yoloTrainingOutputName.trim()) {
      this.notification.showWarning('Please enter an output model name');
      return;
    }

    this.isYoloLoading = true;
    this.yoloService.startTraining({
      dataset_name: this.yoloTrainingDatasetName,
      base_model: this.yoloTrainingBaseModel,
      output_name: this.yoloTrainingOutputName.trim(),
      config: this.yoloTrainingConfig
    }).subscribe({
      next: (response) => {
        if (response.success) {
          this.notification.showSuccess('Training started');
          this.subscribeToYoloTrainingProgress(response.training_id);
          this.loadYoloTrainingJobs();
        } else {
          this.notification.showError(response.message);
        }
        this.isYoloLoading = false;
      },
      error: (err) => {
        this.notification.showError('Failed to start training');
        this.isYoloLoading = false;
      }
    });
  }

  subscribeToYoloTrainingProgress(trainingId: string): void {
    this.closeYoloTrainingStream();

    this.yoloTrainingEventSource = this.yoloService.streamTrainingProgress(trainingId);

    this.yoloTrainingEventSource.onmessage = (event) => {
      const progress = JSON.parse(event.data) as YoloTrainingProgress;
      this.currentYoloTrainingProgress = progress;

      if (progress.status === YoloTrainingStatus.COMPLETED) {
        this.notification.showSuccess('Training completed!');
        this.closeYoloTrainingStream();
        this.loadYoloDashboardData();
      } else if (progress.status === YoloTrainingStatus.FAILED) {
        this.notification.showError(`Training failed: ${progress.error}`);
        this.closeYoloTrainingStream();
      }
    };

    this.yoloTrainingEventSource.onerror = () => {
      this.closeYoloTrainingStream();
    };
  }

  closeYoloTrainingStream(): void {
    if (this.yoloTrainingEventSource) {
      this.yoloTrainingEventSource.close();
      this.yoloTrainingEventSource = null;
    }
  }

  watchYoloTrainingJob(job: TrainingJob): void {
    if (job.status === YoloTrainingStatus.RUNNING || job.status === YoloTrainingStatus.PENDING) {
      this.subscribeToYoloTrainingProgress(job.training_id);
    } else {
      this.yoloService.getTrainingStatus(job.training_id).subscribe({
        next: (response) => {
          this.currentYoloTrainingProgress = response.progress;
        }
      });
    }
  }

  cancelYoloTraining(trainingId: string): void {
    this.yoloService.cancelTraining(trainingId).subscribe({
      next: (response) => {
        if (response.success) {
          this.notification.showSuccess(response.message);
          this.loadYoloTrainingJobs();
        } else {
          this.notification.showError(response.message);
        }
      },
      error: (err) => {
        this.notification.showError('Failed to cancel training');
      }
    });
  }

  getYoloStatusColor(status: YoloTrainingStatus): string {
    switch (status) {
      case YoloTrainingStatus.COMPLETED: return 'green';
      case YoloTrainingStatus.RUNNING: return 'blue';
      case YoloTrainingStatus.FAILED: return 'red';
      case YoloTrainingStatus.CANCELLED: return 'orange';
      default: return 'gray';
    }
  }

  // Annotation callbacks
  onAnnotationSaved(): void {
    this.notification.showSuccess('Annotation saved');
    if (this.annotationDataset) {
      this.yoloService.getDatasetStats(this.annotationDataset).subscribe({
        next: (stats) => {
          this.selectedDataset = stats;
        }
      });
    }
  }

  onAnnotationCancelled(): void {
    this.yoloViewMode = YoloViewMode.Datasets;
  }

  // Format epoch time from seconds to human-readable format
  formatEpochTime(seconds: number | undefined): string {
    if (!seconds) return '-';
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = Math.floor(seconds % 60);
    if (h > 0) {
      return `${h}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
    }
    return `${m}:${s.toString().padStart(2, '0')}`;
  }
}

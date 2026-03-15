import { Component, OnInit, OnDestroy, ChangeDetectorRef, ViewChild, ElementRef, AfterViewChecked } from '@angular/core';
import { Subject, interval } from 'rxjs';
import { takeUntil, switchMap } from 'rxjs/operators';

import { CuredService, TrainedModel, ActiveModelInfo } from '../../services/cured.service';
import { YoloTrainingService } from '../../services/yolo-training.service';
import { NotificationService } from '../../services/notification.service';
import { DatasetService } from '../../services/dataset.service';
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
  Qwen = 'qwen',
  TrOCR = 'trocr'
}

export enum OcrViewMode {
  Datasets = 'datasets',
  Models = 'models',
  Training = 'training',
  Batch = 'batch',
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

  // OCR View Mode (Datasets / Models / Training)
  ocrViewMode: OcrViewMode = OcrViewMode.Datasets;
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
  // ========== Qwen QLoRA Training ==========
  qwenTrainingStatus: TrainingStatus = {
    curatedTexts: 0,
    previousLines: 0,
    newLines: 0,
    totalLines: 0,
    requiredForNextTraining: 30,
    progress: 0,
    isReady: false,
    lastTraining: null,
    currentTraining: null
  };
  qwenModels: TrainedModel[] = [];
  qwenActiveModel: ActiveModelInfo | null = null;
  selectedQwenModel: TrainedModel | null = null;
  qwenModelName = '';
  qwenOutputMode = 'plain';
  qwenOutputModes: { [key: string]: string } = {};
  qwenBaseModels: { id: string; name: string; hf_id: string }[] = [];
  qwenBaseModel = 'qwen3-vl-4b';
  qwenEpochs = 10;
  qwenPatience = 3;
  qwenDevice = 'auto';
  isQwenTraining = false;
  qwenTrainingProgress: any = null;
  qwenEpochHistory: any[] = [];

  // ========== TrOCR Training ==========
  trocrTrainingStatus: TrainingStatus = {
    curatedTexts: 0, previousLines: 0, newLines: 0, totalLines: 0,
    requiredForNextTraining: 30, progress: 0, isReady: false,
    lastTraining: null, currentTraining: null
  };
  trocrModels: TrainedModel[] = [];
  trocrActiveModel: ActiveModelInfo | null = null;
  selectedTrOCRModel: TrainedModel | null = null;
  trocrModelName = '';
  trocrBaseModels: { id: string; name: string; hf_id: string; params: string }[] = [];
  trocrBaseModel = 'trocr-base-handwritten';
  trocrEpochs = 30;
  trocrPatience = 5;
  trocrDevice = 'auto';
  trocrLearningRate = 0.00005;
  trocrFreezeEncoder = false;
  isTrOCRTraining = false;
  trocrTrainingProgress: any = null;
  trocrEpochHistory: any[] = [];

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
  yoloTrainingBaseModel = 'yolov8s.pt';
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
    private cdr: ChangeDetectorRef
  ) {}

  onProductionViewModeChange(mode: string): void {
    setTimeout(() => {
      this.productionViewMode = mode;
      this.cdr.detectChanges();
    });
  }

  ngOnInit(): void {
    this.loadTrainingDatasets();
    this.loadOcrTrainingStatus();
    this.loadAvailableModels();
    this.loadKrakenBaseModels();
    this.loadQwenTrainingStatus();
    this.loadQwenOutputModes();
    this.loadQwenBaseModels();
    this.loadTrOCRTrainingStatus();
    this.loadTrOCRBaseModels();
    this.loadOcrModels();
    this.checkYoloHealth();
    this.loadYoloDashboardData();

    // Poll for training status updates
    this.startTrainingStatusPolling();
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
      this.loadQwenTrainingStatus();
      this.loadTrOCRTrainingStatus();
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

    this.curedService.listQwenModels().subscribe({
      next: (response) => {
        this.qwenModels = response.models;
      },
      error: (err) => console.error('Failed to load Qwen models', err)
    });

    this.curedService.getQwenActiveModel().subscribe({
      next: (model) => {
        this.qwenActiveModel = model;
      },
      error: (err) => console.error('Failed to load Qwen active model', err)
    });

    this.curedService.listTrOCRModels().subscribe({
      next: (response) => {
        this.trocrModels = response.models;
      },
      error: (err) => console.error('Failed to load TrOCR models', err)
    });

    this.curedService.getTrOCRActiveModel().subscribe({
      next: (model) => {
        this.trocrActiveModel = model;
      },
      error: (err) => console.error('Failed to load TrOCR active model', err)
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

  activateQwenModel(modelName: string): void {
    this.curedService.activateQwenModel(modelName).subscribe({
      next: () => {
        this.notification.showSuccess(`Qwen model "${modelName}" activated`);
        this.loadOcrModels();
      },
      error: (err) => this.notification.showError('Failed to activate model')
    });
  }

  deleteQwenModel(modelName: string): void {
    if (!confirm(`Are you sure you want to delete Qwen model "${modelName}"?`)) {
      return;
    }
    this.curedService.deleteQwenModel(modelName).subscribe({
      next: () => {
        this.notification.showSuccess(`Model "${modelName}" deleted`);
        this.selectedQwenModel = null;
        this.loadOcrModels();
      },
      error: (err) => this.notification.showError('Failed to delete model')
    });
  }

  activateTrOCRModel(modelName: string): void {
    this.curedService.activateTrOCRModel(modelName).subscribe({
      next: () => {
        this.notification.showSuccess(`TrOCR model "${modelName}" activated`);
        this.loadOcrModels();
      },
      error: (err) => this.notification.showError('Failed to activate model')
    });
  }

  deleteTrOCRModel(modelName: string): void {
    if (!confirm(`Are you sure you want to delete TrOCR model "${modelName}"?`)) {
      return;
    }
    this.curedService.deleteTrOCRModel(modelName).subscribe({
      next: () => {
        this.notification.showSuccess(`Model "${modelName}" deleted`);
        this.selectedTrOCRModel = null;
        this.loadOcrModels();
      },
      error: (err) => this.notification.showError('Failed to delete model')
    });
  }

  getTrainingStatusColor(status: string): string {
    switch (status) {
      case 'completed': return '#4caf50';
      case 'training': case 'preparing': return '#1976d2';
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
    this.loadQwenTrainingStatus();
    this.loadTrOCRTrainingStatus();
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
  private qwenPollStop$ = new Subject<void>();

  startTrainingStatusPolling(): void {
    // Do a one-time check for each provider; only start polling if training is active
    this.curedService.getKrakenTrainingProgress().subscribe(p => this.handleKrakenProgress(p, true));
    this.curedService.getQwenTrainingProgress().subscribe(p => this.handleQwenProgress(p, true));
    this.curedService.getTrOCRTrainingProgress().subscribe(p => this.handleTrOCRProgress(p, true));
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

  startQwenPolling(): void {
    this.qwenPollStop$.next();
    interval(5000)
      .pipe(
        takeUntil(this.destroy$),
        takeUntil(this.qwenPollStop$),
        switchMap(() => this.curedService.getQwenTrainingProgress())
      )
      .subscribe({ next: (p) => this.handleQwenProgress(p, false) });
  }

  private handleQwenProgress(progress: any, initialCheck: boolean): void {
    if (progress && progress.status !== 'idle') {
      this.qwenTrainingProgress = progress;
      this.isQwenTraining = progress.status === 'training' || progress.status === 'preparing';
      if (progress.epoch_history) {
        this.qwenEpochHistory = progress.epoch_history;
      }
      if (progress.status === 'completed' || progress.status === 'failed') {
        this.qwenPollStop$.next();
        this.loadQwenTrainingStatus();
      } else if (initialCheck) {
        this.startQwenPolling();
      }
    } else {
      this.isQwenTraining = false;
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
    if (engine === TrainingEngine.Qwen) {
      this.loadQwenTrainingStatus();
    } else if (engine === TrainingEngine.TrOCR) {
      this.loadTrOCRTrainingStatus();
    } else {
      this.loadOcrTrainingStatus();
    }
  }

  // ========== Qwen QLoRA Training Methods ==========

  loadQwenTrainingStatus(): void {
    const pids = this.selectedTrainingDatasetIds.length > 0 ? this.selectedTrainingDatasetIds : undefined;
    this.curedService.getQwenTrainingStatus(pids).subscribe({
      next: (status) => {
        this.qwenTrainingStatus = status;
        if (status.currentTraining) {
          this.qwenTrainingProgress = status.currentTraining;
          this.isQwenTraining = status.currentTraining.status === 'training' ||
                                 status.currentTraining.status === 'preparing';
          if (status.currentTraining.epoch_history) {
            this.qwenEpochHistory = status.currentTraining.epoch_history;
          }
        }
      },
      error: (err) => {
        console.error('Failed to load Qwen training status', err);
      }
    });
  }

  loadQwenOutputModes(): void {
    this.curedService.getQwenOutputModes().subscribe({
      next: (response) => {
        this.qwenOutputModes = response.modes;
      },
      error: (err) => {
        console.error('Failed to load Qwen output modes', err);
        this.qwenOutputModes = {
          plain: 'Plain text transcription',
          tei_lex0: 'TEI Lex-0 XML for dictionaries',
          tei_epidoc: 'TEI EpiDoc XML for cuneiform texts',
        };
      }
    });
  }

  loadQwenBaseModels(): void {
    this.curedService.getQwenBaseModels().subscribe({
      next: (response) => {
        this.qwenBaseModels = response.models;
        if (response.models.length > 0 && !this.qwenBaseModel) {
          this.qwenBaseModel = response.models[0].id;
        }
      },
      error: (err) => {
        console.error('Failed to load Qwen base models', err);
        this.qwenBaseModels = [
          { id: 'qwen3-vl-4b', name: 'Qwen3-VL 4B', hf_id: 'Qwen/Qwen3-VL-4B' },
          { id: 'qwen3-vl-8b', name: 'Qwen3-VL 8B', hf_id: 'Qwen/Qwen3-VL-8B' },
        ];
      }
    });
  }

  startQwenTraining(): void {
    if (!this.qwenModelName?.trim()) {
      this.notification.showWarning('Please enter a model name');
      return;
    }

    this.isQwenTraining = true;
    this.qwenEpochHistory = [];

    const pids = this.selectedTrainingDatasetIds.length > 0 ? this.selectedTrainingDatasetIds : undefined;
    this.curedService.startQwenTraining(
      this.qwenEpochs,
      this.qwenModelName.trim(),
      this.qwenBaseModel,
      this.qwenOutputMode,
      this.qwenDevice,
      this.qwenPatience,
      pids
    ).subscribe({
      next: (response) => {
        this.notification.showSuccess('Qwen QLoRA training started');
        this.trainingRightTab = 'progress';
        this.startQwenPolling();
        this.loadQwenTrainingStatus();
      },
      error: (err) => {
        this.notification.showError('Failed to start training: ' + (err.error?.detail || err.message));
        this.isQwenTraining = false;
      }
    });
  }

  cancelQwenTraining(): void {
    this.curedService.cancelQwenTraining().subscribe({
      next: () => {
        this.notification.showSuccess('Training cancelled');
        this.isQwenTraining = false;
        this.loadQwenTrainingStatus();
      },
      error: (err) => {
        this.notification.showError('Failed to cancel training');
      }
    });
  }

  // ========== TrOCR Training Methods ==========

  private trocrPollStop$ = new Subject<void>();

  loadTrOCRTrainingStatus(): void {
    const pids = this.selectedTrainingDatasetIds.length > 0 ? this.selectedTrainingDatasetIds : undefined;
    this.curedService.getTrOCRTrainingStatus(pids).subscribe({
      next: (status) => {
        this.trocrTrainingStatus = status;
        if (status.currentTraining) {
          this.trocrTrainingProgress = status.currentTraining;
          this.isTrOCRTraining = status.currentTraining.status === 'training' ||
                                  status.currentTraining.status === 'preparing';
          if (status.currentTraining.epoch_history) {
            this.trocrEpochHistory = status.currentTraining.epoch_history;
          }
        }
      },
      error: (err) => console.error('Failed to load TrOCR training status', err)
    });
  }

  loadTrOCRBaseModels(): void {
    this.curedService.getTrOCRBaseModels().subscribe({
      next: (response) => {
        this.trocrBaseModels = response.models;
        if (response.models.length > 0 && !this.trocrBaseModel) {
          this.trocrBaseModel = response.models[0].id;
        }
      },
      error: (err) => {
        console.error('Failed to load TrOCR base models', err);
        this.trocrBaseModels = [
          { id: 'trocr-base-handwritten', name: 'TrOCR Base Handwritten', hf_id: 'microsoft/trocr-base-handwritten', params: '~334M' },
          { id: 'trocr-small-handwritten', name: 'TrOCR Small Handwritten', hf_id: 'microsoft/trocr-small-handwritten', params: '~62M' },
        ];
      }
    });
  }

  startTrOCRPolling(): void {
    this.trocrPollStop$.next();
    interval(5000)
      .pipe(
        takeUntil(this.destroy$),
        takeUntil(this.trocrPollStop$),
        switchMap(() => this.curedService.getTrOCRTrainingProgress())
      )
      .subscribe({ next: (p) => this.handleTrOCRProgress(p, false) });
  }

  private handleTrOCRProgress(progress: any, initialCheck: boolean): void {
    if (progress && progress.status !== 'idle') {
      this.trocrTrainingProgress = progress;
      this.isTrOCRTraining = progress.status === 'training' || progress.status === 'preparing';
      if (progress.epoch_history) {
        this.trocrEpochHistory = progress.epoch_history;
      }
      if (progress.status === 'completed' || progress.status === 'failed') {
        this.trocrPollStop$.next();
        this.loadTrOCRTrainingStatus();
      } else if (initialCheck) {
        this.startTrOCRPolling();
      }
    } else {
      this.isTrOCRTraining = false;
    }
  }

  startTrOCRTraining(): void {
    if (!this.trocrModelName?.trim()) {
      this.notification.showWarning('Please enter a model name');
      return;
    }

    this.isTrOCRTraining = true;
    this.trocrEpochHistory = [];

    const pids = this.selectedTrainingDatasetIds.length > 0 ? this.selectedTrainingDatasetIds : undefined;
    this.curedService.startTrOCRTraining(
      this.trocrEpochs,
      this.trocrModelName.trim(),
      this.trocrBaseModel,
      this.trocrDevice,
      this.trocrPatience,
      this.trocrLearningRate,
      this.trocrFreezeEncoder,
      pids
    ).subscribe({
      next: (response) => {
        this.notification.showSuccess('TrOCR training started');
        this.trainingRightTab = 'progress';
        this.startTrOCRPolling();
        this.loadTrOCRTrainingStatus();
      },
      error: (err) => {
        this.notification.showError('Failed to start training: ' + (err.error?.detail || err.message));
        this.isTrOCRTraining = false;
      }
    });
  }

  cancelTrOCRTraining(): void {
    this.curedService.cancelTrOCRTraining().subscribe({
      next: () => {
        this.notification.showSuccess('TrOCR training cancelled');
        this.isTrOCRTraining = false;
        this.loadTrOCRTrainingStatus();
      },
      error: (err) => this.notification.showError('Failed to cancel training')
    });
  }

  // ========== YOLO Training Methods ==========

  checkYoloHealth(): void {
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

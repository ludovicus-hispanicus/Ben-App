import { Component, OnInit, OnDestroy, ChangeDetectorRef } from '@angular/core';
import { Subject, interval } from 'rxjs';
import { takeUntil, switchMap } from 'rxjs/operators';

import { CuredService, TrainedModel, ActiveModelInfo } from '../../services/cured.service';
import { YoloTrainingService } from '../../services/yolo-training.service';
import { NotificationService } from '../../services/notification.service';
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
  DeepSeek = 'deepseek',
  Qwen = 'qwen'
}

export enum OcrViewMode {
  Datasets = 'datasets',
  Models = 'models',
  Training = 'training',
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
export class TrainingComponent implements OnInit, OnDestroy {
  private destroy$ = new Subject<void>();

  // OCR View Mode (Datasets / Models / Training)
  ocrViewMode: OcrViewMode = OcrViewMode.Datasets;
  OcrViewMode = OcrViewMode;

  // CuReD stage (0=dashboard, 1=pdf, 2+=visualizer)
  curedStage = 0;
  // Production view mode ('dashboard' or 'editor')
  productionViewMode: string = 'dashboard';

  get hideChrome(): boolean {
    return (this.curedStage >= 2 && this.ocrViewMode === OcrViewMode.Datasets)
        || (this.ocrViewMode === OcrViewMode.Export && this.productionViewMode === 'editor');
  }

  // Tab state (legacy)
  activeTab: TrainingTab = TrainingTab.CuReD;
  TrainingTab = TrainingTab;

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

  // Training engine toggle (Kraken vs DeepSeek)
  trainingEngine: TrainingEngine = TrainingEngine.Kraken;
  TrainingEngine = TrainingEngine;

  // Training right panel tabs
  trainingRightTab: 'progress' | 'jobs' = 'jobs';

  // ========== OCR Models ==========
  krakenModels: TrainedModel[] = [];
  krakenActiveModel: ActiveModelInfo | null = null;
  selectedKrakenModel: TrainedModel | null = null;
  deepseekModels: TrainedModel[] = [];
  deepseekActiveModel: ActiveModelInfo | null = null;
  selectedDeepseekModel: TrainedModel | null = null;

  // ========== DeepSeek QLoRA Training ==========
  deepseekTrainingStatus: TrainingStatus = {
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
  deepseekModelName = '';
  deepseekOutputMode = 'plain';
  deepseekOutputModes: { [key: string]: string } = {};
  deepseekEpochs = 10;
  deepseekPatience = 3;
  deepseekDevice = 'auto';
  isDeepSeekTraining = false;
  deepseekTrainingProgress: any = null;
  deepseekEpochHistory: any[] = [];

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
    private cdr: ChangeDetectorRef
  ) {}

  onProductionViewModeChange(mode: string): void {
    setTimeout(() => {
      this.productionViewMode = mode;
      this.cdr.detectChanges();
    });
  }

  ngOnInit(): void {
    this.loadOcrTrainingStatus();
    this.loadAvailableModels();
    this.loadKrakenBaseModels();
    this.loadDeepSeekTrainingStatus();
    this.loadDeepSeekOutputModes();
    this.loadQwenTrainingStatus();
    this.loadQwenOutputModes();
    this.loadQwenBaseModels();
    this.loadOcrModels();
    this.checkYoloHealth();
    this.loadYoloDashboardData();

    // Poll for training status updates
    this.startTrainingStatusPolling();
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
      this.loadQwenTrainingStatus();
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

    this.curedService.getDeepSeekActiveModel().subscribe({
      next: (model) => {
        this.deepseekActiveModel = model;
      },
      error: (err) => console.error('Failed to load DeepSeek active model', err)
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

  activateDeepseekModel(modelName: string): void {
    this.curedService.activateDeepSeekModel(modelName).subscribe({
      next: () => {
        this.notification.showSuccess(`DeepSeek model "${modelName}" activated`);
        this.loadOcrModels();
      },
      error: (err) => this.notification.showError('Failed to activate model')
    });
  }

  deleteDeepseekModel(modelName: string): void {
    if (!confirm(`Are you sure you want to delete DeepSeek model "${modelName}"?`)) {
      return;
    }
    this.curedService.deleteDeepSeekModel(modelName).subscribe({
      next: () => {
        this.notification.showSuccess(`Model "${modelName}" deleted`);
        this.selectedDeepseekModel = null;
        this.loadOcrModels();
      },
      error: (err) => this.notification.showError('Failed to delete model')
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

  getTrainingStatusColor(status: string): string {
    switch (status) {
      case 'completed': return '#4caf50';
      case 'training': case 'preparing': return '#1976d2';
      case 'failed': return '#f44336';
      case 'cancelled': return '#ff9800';
      default: return '#666';
    }
  }

  // ========== CuReD OCR Training Methods ==========

  loadOcrTrainingStatus(): void {
    this.curedService.getKrakenTrainingStatus().subscribe({
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

  startTrainingStatusPolling(): void {
    // Poll Kraken training progress
    interval(5000)
      .pipe(
        takeUntil(this.destroy$),
        switchMap(() => this.curedService.getKrakenTrainingProgress())
      )
      .subscribe({
        next: (progress) => {
          if (progress && progress.status !== 'idle') {
            this.ocrTrainingProgress = progress;
            this.isOcrTraining = progress.status === 'training' || progress.status === 'preparing';
            if (progress.epoch_history) {
              this.epochHistory = progress.epoch_history;
            }
            if (progress.status === 'completed' || progress.status === 'failed') {
              this.loadOcrTrainingStatus();
            }
          } else {
            this.isOcrTraining = false;
          }
        }
      });

    // Poll DeepSeek training progress
    interval(5000)
      .pipe(
        takeUntil(this.destroy$),
        switchMap(() => this.curedService.getDeepSeekTrainingProgress())
      )
      .subscribe({
        next: (progress) => {
          if (progress && progress.status !== 'idle') {
            this.deepseekTrainingProgress = progress;
            this.isDeepSeekTraining = progress.status === 'training' || progress.status === 'preparing';
            if (progress.epoch_history) {
              this.deepseekEpochHistory = progress.epoch_history;
            }
            if (progress.status === 'completed' || progress.status === 'failed') {
              this.loadDeepSeekTrainingStatus();
            }
          } else {
            this.isDeepSeekTraining = false;
          }
        }
      });

    // Poll Qwen training progress
    interval(5000)
      .pipe(
        takeUntil(this.destroy$),
        switchMap(() => this.curedService.getQwenTrainingProgress())
      )
      .subscribe({
        next: (progress) => {
          if (progress && progress.status !== 'idle') {
            this.qwenTrainingProgress = progress;
            this.isQwenTraining = progress.status === 'training' || progress.status === 'preparing';
            if (progress.epoch_history) {
              this.qwenEpochHistory = progress.epoch_history;
            }
            if (progress.status === 'completed' || progress.status === 'failed') {
              this.loadQwenTrainingStatus();
            }
          } else {
            this.isQwenTraining = false;
          }
        }
      });
  }

  startOcrTraining(): void {
    if (!this.trainingModelName?.trim()) {
      this.notification.showWarning('Please enter a model name');
      return;
    }

    this.isOcrTraining = true;
    this.epochHistory = [];

    const baseModel = this.selectedBaseModel === 'from_scratch' ? null : this.selectedBaseModel;
    this.curedService.startKrakenTraining(this.krakenEpochs, this.trainingModelName.trim(), baseModel, this.krakenBatchSize, this.krakenDevice, this.krakenPatience).subscribe({
      next: (response) => {
        this.notification.showSuccess('Kraken training started');
        this.trainingRightTab = 'progress';
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

  // ========== DeepSeek QLoRA Training Methods ==========

  setTrainingEngine(engine: TrainingEngine): void {
    this.trainingEngine = engine;
    if (engine === TrainingEngine.DeepSeek) {
      this.loadDeepSeekTrainingStatus();
    } else if (engine === TrainingEngine.Qwen) {
      this.loadQwenTrainingStatus();
    } else {
      this.loadOcrTrainingStatus();
    }
  }

  loadDeepSeekTrainingStatus(): void {
    this.curedService.getDeepSeekTrainingStatus().subscribe({
      next: (status) => {
        this.deepseekTrainingStatus = status;
        if (status.currentTraining) {
          this.deepseekTrainingProgress = status.currentTraining;
          this.isDeepSeekTraining = status.currentTraining.status === 'training' ||
                                     status.currentTraining.status === 'preparing';
          if (status.currentTraining.epoch_history) {
            this.deepseekEpochHistory = status.currentTraining.epoch_history;
          }
        }
      },
      error: (err) => {
        console.error('Failed to load DeepSeek training status', err);
      }
    });
  }

  loadDeepSeekOutputModes(): void {
    this.curedService.getDeepSeekOutputModes().subscribe({
      next: (response) => {
        this.deepseekOutputModes = response.modes;
      },
      error: (err) => {
        console.error('Failed to load DeepSeek output modes', err);
        // Provide defaults
        this.deepseekOutputModes = {
          plain: 'Plain text transcription',
          tei_lex0: 'TEI Lex-0 XML for dictionaries',
          tei_epidoc: 'TEI EpiDoc XML for cuneiform texts',
        };
      }
    });
  }

  startDeepSeekTraining(): void {
    if (!this.deepseekModelName?.trim()) {
      this.notification.showWarning('Please enter a model name');
      return;
    }

    this.isDeepSeekTraining = true;
    this.deepseekEpochHistory = [];

    this.curedService.startDeepSeekTraining(
      this.deepseekEpochs,
      this.deepseekModelName.trim(),
      this.deepseekOutputMode,
      this.deepseekDevice,
      this.deepseekPatience
    ).subscribe({
      next: (response) => {
        this.notification.showSuccess('DeepSeek QLoRA training started');
        this.trainingRightTab = 'progress';
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
      next: () => {
        this.notification.showSuccess('Training cancelled');
        this.isDeepSeekTraining = false;
        this.loadDeepSeekTrainingStatus();
      },
      error: (err) => {
        this.notification.showError('Failed to cancel training');
      }
    });
  }

  // ========== Qwen QLoRA Training Methods ==========

  loadQwenTrainingStatus(): void {
    this.curedService.getQwenTrainingStatus().subscribe({
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

    this.curedService.startQwenTraining(
      this.qwenEpochs,
      this.qwenModelName.trim(),
      this.qwenBaseModel,
      this.qwenOutputMode,
      this.qwenDevice,
      this.qwenPatience
    ).subscribe({
      next: (response) => {
        this.notification.showSuccess('Qwen QLoRA training started');
        this.trainingRightTab = 'progress';
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

import { Component, OnInit, OnDestroy, ViewChild, ElementRef } from '@angular/core';
import { MatDialog } from '@angular/material/dialog';
import { Subject, interval } from 'rxjs';
import { takeUntil, switchMap } from 'rxjs/operators';

import { YoloTrainingService } from '../../services/yolo-training.service';
import { NotificationService } from '../../services/notification.service';
import {
  DatasetListItem,
  DatasetStats,
  ModelInfo,
  TrainingConfig,
  TrainingProgress,
  TrainingStatus,
  TrainingJob,
  DEFAULT_TRAINING_CONFIG,
  YoloHealthResponse,
  YoloClass,
  CLASS_COLORS
} from '../../models/yolo-training';

export enum ViewMode {
  Dashboard = 'dashboard',
  Datasets = 'datasets',
  Models = 'models',
  Training = 'training',
  Annotate = 'annotate'
}

@Component({
  selector: 'app-yolo-training',
  templateUrl: './yolo-training.component.html',
  styleUrls: ['./yolo-training.component.scss']
})
export class YoloTrainingComponent implements OnInit, OnDestroy {
  private destroy$ = new Subject<void>();

  // View state
  viewMode: ViewMode = ViewMode.Dashboard;
  ViewMode = ViewMode;
  isLoading = false;
  healthStatus: YoloHealthResponse | null = null;

  // Datasets
  datasets: DatasetListItem[] = [];
  selectedDataset: DatasetStats | null = null;

  // Models
  models: ModelInfo[] = [];
  baseModels: string[] = [];
  selectedModel: ModelInfo | null = null;

  // Training
  trainingConfig: TrainingConfig = { ...DEFAULT_TRAINING_CONFIG };
  activeTrainingJobs: TrainingJob[] = [];
  currentTrainingProgress: TrainingProgress | null = null;
  private trainingEventSource: EventSource | null = null;

  // New dataset form
  newDatasetName = '';
  newDatasetClasses: string[] = ['entry', 'subentry', 'guidewords'];
  newDatasetDescription = '';

  // Training form
  trainingDatasetName = '';
  trainingBaseModel = 'yolov8s.pt';
  trainingOutputName = '';

  // Annotation state
  annotationDataset: string = '';
  annotationClasses: YoloClass[] = [];

  // Class colors for display
  classColors = CLASS_COLORS;

  constructor(
    private yoloService: YoloTrainingService,
    private notification: NotificationService,
    private dialog: MatDialog
  ) {}

  ngOnInit(): void {
    this.checkHealth();
    this.loadDashboardData();
  }

  ngOnDestroy(): void {
    this.destroy$.next();
    this.destroy$.complete();
    this.closeTrainingStream();
  }

  // ============== Health & Dashboard ==============

  checkHealth(): void {
    this.yoloService.checkHealth().subscribe({
      next: (response) => {
        this.healthStatus = response;
      },
      error: (err) => {
        this.healthStatus = { status: 'unhealthy', error: err.message };
      }
    });
  }

  loadDashboardData(): void {
    this.isLoading = true;

    // Load datasets
    this.yoloService.listDatasets().subscribe({
      next: (datasets) => {
        this.datasets = datasets;
      },
      error: (err) => {
        this.notification.showError('Failed to load datasets');
      }
    });

    // Load models
    this.yoloService.listModels().subscribe({
      next: (response) => {
        this.models = response.models;
        this.baseModels = response.base_models;
        this.isLoading = false;
      },
      error: (err) => {
        this.notification.showError('Failed to load models');
        this.isLoading = false;
      }
    });

    // Load training jobs
    this.loadTrainingJobs();
  }

  loadTrainingJobs(): void {
    this.yoloService.listTrainingJobs().subscribe({
      next: (jobs) => {
        this.activeTrainingJobs = jobs;
      },
      error: (err) => {
        console.error('Failed to load training jobs', err);
      }
    });
  }

  // ============== View Navigation ==============

  setViewMode(mode: ViewMode): void {
    this.viewMode = mode;
    if (mode === ViewMode.Dashboard) {
      this.loadDashboardData();
    }
  }

  // ============== Dataset Management ==============

  createDataset(): void {
    if (!this.newDatasetName.trim()) {
      this.notification.showWarning('Please enter a dataset name');
      return;
    }

    if (this.newDatasetClasses.length === 0) {
      this.notification.showWarning('Please add at least one class');
      return;
    }

    this.isLoading = true;
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
          this.loadDashboardData();
        } else {
          this.notification.showError(response.message);
        }
        this.isLoading = false;
      },
      error: (err) => {
        this.notification.showError('Failed to create dataset');
        this.isLoading = false;
      }
    });
  }

  selectDataset(dataset: DatasetListItem): void {
    this.isLoading = true;
    this.yoloService.getDatasetStats(dataset.dataset_id).subscribe({
      next: (stats) => {
        this.selectedDataset = stats;
        this.isLoading = false;
      },
      error: (err) => {
        this.notification.showError('Failed to load dataset details');
        this.isLoading = false;
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
          this.loadDashboardData();
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
    this.viewMode = ViewMode.Annotate;
  }

  // ============== Model Management ==============

  selectModel(model: ModelInfo): void {
    this.selectedModel = model;
  }

  deleteModel(modelName: string): void {
    if (!confirm(`Are you sure you want to delete model "${modelName}"?`)) {
      return;
    }

    this.yoloService.deleteModel(modelName).subscribe({
      next: (response) => {
        if (response.success) {
          this.notification.showSuccess(response.message);
          this.selectedModel = null;
          this.loadDashboardData();
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

  // ============== Training ==============

  startTraining(): void {
    if (!this.trainingDatasetName) {
      this.notification.showWarning('Please select a dataset');
      return;
    }

    if (!this.trainingOutputName.trim()) {
      this.notification.showWarning('Please enter an output model name');
      return;
    }

    this.isLoading = true;
    this.yoloService.startTraining({
      dataset_name: this.trainingDatasetName,
      base_model: this.trainingBaseModel,
      output_name: this.trainingOutputName.trim(),
      config: this.trainingConfig
    }).subscribe({
      next: (response) => {
        if (response.success) {
          this.notification.showSuccess('Training started');
          this.subscribeToTrainingProgress(response.training_id);
          this.loadTrainingJobs();
        } else {
          this.notification.showError(response.message);
        }
        this.isLoading = false;
      },
      error: (err) => {
        this.notification.showError('Failed to start training');
        this.isLoading = false;
      }
    });
  }

  subscribeToTrainingProgress(trainingId: string): void {
    this.closeTrainingStream();

    this.trainingEventSource = this.yoloService.streamTrainingProgress(trainingId);

    this.trainingEventSource.onmessage = (event) => {
      const progress = JSON.parse(event.data) as TrainingProgress;
      this.currentTrainingProgress = progress;

      if (progress.status === TrainingStatus.COMPLETED) {
        this.notification.showSuccess('Training completed!');
        this.closeTrainingStream();
        this.loadDashboardData();
      } else if (progress.status === TrainingStatus.FAILED) {
        this.notification.showError(`Training failed: ${progress.error}`);
        this.closeTrainingStream();
      }
    };

    this.trainingEventSource.onerror = (error) => {
      console.error('Training stream error', error);
      this.closeTrainingStream();
    };
  }

  closeTrainingStream(): void {
    if (this.trainingEventSource) {
      this.trainingEventSource.close();
      this.trainingEventSource = null;
    }
  }

  watchTrainingJob(job: TrainingJob): void {
    if (job.status === TrainingStatus.RUNNING || job.status === TrainingStatus.PENDING) {
      this.subscribeToTrainingProgress(job.training_id);
    } else {
      this.yoloService.getTrainingStatus(job.training_id).subscribe({
        next: (response) => {
          this.currentTrainingProgress = response.progress;
        }
      });
    }
  }

  cancelTraining(trainingId: string): void {
    this.yoloService.cancelTraining(trainingId).subscribe({
      next: (response) => {
        if (response.success) {
          this.notification.showSuccess(response.message);
          this.loadTrainingJobs();
        } else {
          this.notification.showError(response.message);
        }
      },
      error: (err) => {
        this.notification.showError('Failed to cancel training');
      }
    });
  }

  getStatusColor(status: TrainingStatus): string {
    switch (status) {
      case TrainingStatus.COMPLETED: return 'green';
      case TrainingStatus.RUNNING: return 'blue';
      case TrainingStatus.FAILED: return 'red';
      case TrainingStatus.CANCELLED: return 'orange';
      default: return 'gray';
    }
  }

  // ============== Annotation Callbacks ==============

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
    this.viewMode = ViewMode.Datasets;
  }
}

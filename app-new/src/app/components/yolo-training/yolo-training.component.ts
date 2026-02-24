import { Component, OnInit, OnDestroy, ViewChild, ElementRef, AfterViewInit } from '@angular/core';
import { ActivatedRoute } from '@angular/router';
import { MatDialog } from '@angular/material/dialog';
import { Subject, Subscription, interval } from 'rxjs';
import { takeUntil, switchMap } from 'rxjs/operators';
import * as JSZip from 'jszip';

import { YoloTrainingService } from '../../services/yolo-training.service';
import { NotificationService } from '../../services/notification.service';
import { ImageBrowserDialogComponent } from '../common/image-browser-dialog/image-browser-dialog.component';
import { FolderPickerDialogComponent, FolderPickerResult } from '../common/folder-picker-dialog/folder-picker-dialog.component';
import { SelectedPage } from '../../models/pages';
import { PagesService } from '../../services/pages.service';
import { HttpClient } from '@angular/common/http';
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
  CLASS_COLORS,
  Detection,
  getClassColor,
  AutoAnnotateRequest,
  AutoAnnotateResponse,
  AutoAnnotateStatus
} from '../../models/yolo-training';

export enum ViewMode {
  Datasets = 'datasets',
  Models = 'models',
  Training = 'training',
  Annotate = 'annotate',
  Predict = 'predict'
}

@Component({
  selector: 'app-yolo-training',
  templateUrl: './yolo-training.component.html',
  styleUrls: ['./yolo-training.component.scss']
})
export class YoloTrainingComponent implements OnInit, OnDestroy {
  private destroy$ = new Subject<void>();

  // View state
  viewMode: ViewMode = ViewMode.Datasets;
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
  activeModelId: string | null = null;

  // Training
  trainingConfig: TrainingConfig = { ...DEFAULT_TRAINING_CONFIG };
  activeTrainingJobs: TrainingJob[] = [];
  currentTrainingProgress: TrainingProgress | null = null;
  private trainingEventSource: EventSource | null = null;
  trainingRightTab: 'progress' | 'jobs' = 'jobs';
  trainingLogs: any[] = [];
  trainingLogsLoading = false;
  currentViewedTrainingId: string | null = null;
  logsAutoRefreshing = false;
  private logsRefreshSub: Subscription | null = null;

  // Inline editing
  editingField: 'name' | null = null;

  // New dataset form
  newDatasetName = '';
  newDatasetClasses: string[] = ['entry', 'subentry', 'guidewords'];

  // Training form
  trainingDatasetName = '';
  trainingBaseModel = 'yolov8s.pt';
  trainingOutputName = '';

  // Annotation state
  annotationDataset: string = '';
  annotationClasses: YoloClass[] = [];

  // Class colors for display
  classColors = CLASS_COLORS;

  // Predict state
  @ViewChild('predictCanvas') predictCanvasRef: ElementRef<HTMLCanvasElement>;
  predictImage: string | null = null;
  predictImageUrl: string | null = null;
  predictModel: string = 'default';
  predictConfidence: number = 0.25;
  predictIou: number = 0.45;
  predictDetections: Detection[] = [];
  predictProcessingTime: number = 0;
  predictModelUsed: string = '';
  isPredicting: boolean = false;
  private predictImageElement: HTMLImageElement | null = null;

  // Extracted detection crops
  extractMinConfidence: number = 0.50;
  extractedDetections: { dataUrl: string; className: string; confidence: number; index: number }[] = [];

  // Batch prediction
  isBatchProcessing: boolean = false;
  batchTotal: number = 0;
  batchProcessed: number = 0;
  batchFailed: number = 0;
  batchTotalDetections: number = 0;

  // Auto-annotate
  autoAnnotateFormVisible: boolean = false;
  autoAnnotateProjectId: string = '';
  autoAnnotateProjectName: string = '';
  autoAnnotateModel: string = '';
  autoAnnotateDatasetName: string = '';
  autoAnnotateConfidence: number = 0.25;
  autoAnnotateIou: number = 0.45;
  autoAnnotateValRatio: number = 0.2;
  autoAnnotateJobId: string | null = null;
  autoAnnotateStatus: AutoAnnotateStatus | null = null;
  isAutoAnnotating: boolean = false;
  private autoAnnotatePollSub: any = null;

  constructor(
    private yoloService: YoloTrainingService,
    private notification: NotificationService,
    private dialog: MatDialog,
    private http: HttpClient,
    private route: ActivatedRoute,
    private pagesService: PagesService
  ) {}

  ngOnInit(): void {
    this.checkHealth();
    this.loadDashboardData();
    this.loadActiveModel();

    this.route.queryParams.subscribe(params => {
      if (params['library_project'] && params['library_page']) {
        this.loadFromLibrary(params['library_project'], parseInt(params['library_page']));
      }
    });
  }

  ngOnDestroy(): void {
    this.destroy$.next();
    this.destroy$.complete();
    this.closeTrainingStream();
    this.stopLogsAutoRefresh();
    this.stopAutoAnnotatePoll();
    if (this.predictImageUrl) {
      URL.revokeObjectURL(this.predictImageUrl);
    }
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

        // Auto-connect to a running job if nothing is currently being viewed
        if (!this.currentViewedTrainingId) {
          const runningJob = jobs.find(
            j => j.status === TrainingStatus.RUNNING || j.status === TrainingStatus.PENDING
          );
          if (runningJob) {
            this.watchTrainingJob(runningJob);
          }
        }
      },
      error: (err) => {
        console.error('Failed to load training jobs', err);
      }
    });
  }

  loadActiveModel(): void {
    this.yoloService.getActiveModel().subscribe({
      next: (response) => {
        this.activeModelId = response.model_name;
        // Default training base model to the active trained model
        if (this.activeModelId) {
          this.trainingBaseModel = this.activeModelId + '/best.pt';
        }
      },
      error: () => {
        this.activeModelId = null;
      }
    });
  }

  // ============== View Navigation ==============

  setViewMode(mode: ViewMode): void {
    this.viewMode = mode;
    if (mode === ViewMode.Datasets) {
      this.loadDashboardData();
    }
    if (mode === ViewMode.Models || mode === ViewMode.Predict) {
      this.loadActiveModel();
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
      classes: this.newDatasetClasses
    }).subscribe({
      next: (response) => {
        if (response.success) {
          this.notification.showSuccess(`Dataset "${response.name}" created`);
          this.newDatasetName = '';
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

  closeDataset(): void {
    this.selectedDataset = null;
  }

  startEditDatasetField(field: 'name'): void {
    this.editingField = field;
    setTimeout(() => {
      const input = document.querySelector('.edit-dataset-input') as HTMLInputElement;
      if (input) { input.focus(); input.select(); }
    });
  }

  finishEditDatasetField(field: 'name', event: Event): void {
    const newValue = (event.target as HTMLInputElement).value.trim();
    this.editingField = null;
    if (!this.selectedDataset) return;

    const oldValue = this.selectedDataset.name;
    if (!newValue) return;
    if (newValue === oldValue) return;

    this.selectedDataset.name = newValue;

    this.yoloService.updateDatasetMetadata(this.selectedDataset.dataset_id, { name: newValue }).subscribe({
      next: (response) => {
        if (response.success) {
          const listItem = this.datasets.find(d => d.dataset_id === response.dataset_id);
          if (listItem) {
            listItem.name = response.name;
          }
        }
      },
      error: () => {
        if (this.selectedDataset) {
          this.selectedDataset.name = oldValue;
        }
        this.notification.showError('Failed to update name');
      }
    });
  }

  downloadDataset(format: 'training' | 'snippets'): void {
    if (!this.selectedDataset) return;
    this.yoloService.downloadDataset(this.selectedDataset.dataset_id, format);
  }

  saveSnippetsToLibrary(): void {
    if (!this.selectedDataset) return;

    const dialogRef = this.dialog.open(FolderPickerDialogComponent, {
      width: '550px',
      data: { title: 'Save Snippets to Library' }
    });

    dialogRef.afterClosed().subscribe((result: FolderPickerResult | null) => {
      if (!result) return;

      this.notification.showInfo('Saving snippets to library...');
      this.yoloService.saveSnippetsToLibrary(
        this.selectedDataset.dataset_id,
        result.project_id,
        result.project_name
      ).subscribe({
        next: (response) => {
          this.notification.showSuccess(
            `Saved ${response.snippet_count} snippets to "${response.name}"`
          );
        },
        error: (err) => {
          this.notification.showError('Failed to save snippets: ' + (err.error?.detail || err.message));
        }
      });
    });
  }

  // Multi-merge selections
  mergeSelections: { [datasetId: string]: boolean } = {};

  toggleMergeSelection(datasetId: string): void {
    if (this.selectedDataset && datasetId === this.selectedDataset.dataset_id) return;
    this.mergeSelections[datasetId] = !this.mergeSelections[datasetId];
  }

  getMergeSelectedCount(): number {
    return Object.values(this.mergeSelections).filter(v => v).length;
  }

  startMultiMerge(): void {
    if (!this.selectedDataset) return;

    const selectedIds = Object.entries(this.mergeSelections)
      .filter(([_, selected]) => selected)
      .map(([id]) => id);

    if (selectedIds.length === 0) return;

    const defaultName = `${this.selectedDataset.name}_merged`;
    const targetName = prompt('Name for the merged dataset:', defaultName);
    if (!targetName || !targetName.trim()) return;

    const allSources = [this.selectedDataset.dataset_id, ...selectedIds];

    this.isLoading = true;
    this.yoloService.mergeDatasets(allSources, targetName.trim()).subscribe({
      next: (response: any) => {
        this.isLoading = false;
        if (response.success) {
          this.notification.showSuccess(
            `Merged ${allSources.length} datasets into "${targetName}" — ${response.total_images} images, ${response.class_count} classes`
          );
          this.loadDashboardData();
          setTimeout(() => {
            const newDs = this.datasets.find((d: any) => d.dataset_id === response.dataset_id);
            if (newDs) this.selectDataset(newDs);
          }, 500);
        } else {
          this.notification.showError(response.message || 'Merge failed');
        }
      },
      error: (err: any) => {
        this.isLoading = false;
        this.notification.showError(err?.error?.detail || 'Failed to merge datasets');
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

  addClassToExistingDataset(): void {
    if (!this.selectedDataset) return;

    const className = prompt('Enter new class name:');
    if (!className || !className.trim()) return;

    const existing = this.selectedDataset.classes.map(c => c.name);
    if (existing.includes(className.trim())) {
      this.notification.showWarning(`Class "${className.trim()}" already exists`);
      return;
    }

    this.yoloService.addClassesToDataset(this.selectedDataset.dataset_id, [className.trim()]).subscribe({
      next: (response) => {
        if (response.success) {
          this.notification.showSuccess(response.message);
          this.selectDataset({ dataset_id: this.selectedDataset.dataset_id } as any);
        } else {
          this.notification.showError(response.message);
        }
      },
      error: (err) => {
        this.notification.showError('Failed to add class');
      }
    });
  }

  openAnnotation(dataset: DatasetStats | DatasetListItem): void {
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

  activateModel(modelId: string): void {
    this.yoloService.activateModel(modelId).subscribe({
      next: (response) => {
        if (response.success) {
          this.activeModelId = modelId;
          this.notification.showSuccess(`Model "${modelId}" activated`);
        }
      },
      error: (err) => {
        this.notification.showError('Failed to activate model');
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
          this.currentViewedTrainingId = response.training_id;
          this.subscribeToTrainingProgress(response.training_id);
          this.startLogsAutoRefresh(response.training_id);
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
        this.loadTrainingLogs(trainingId);
        this.closeTrainingStream();
        this.stopLogsAutoRefresh();
        this.loadDashboardData();
      } else if (progress.status === TrainingStatus.FAILED) {
        this.notification.showError(`Training failed: ${progress.error}`);
        this.loadTrainingLogs(trainingId);
        this.closeTrainingStream();
        this.stopLogsAutoRefresh();
      }
    };

    this.trainingEventSource.onerror = (error) => {
      console.warn('Training stream error, will retry...', error);
      // EventSource auto-reconnects by default; only close if CLOSED state
      if (this.trainingEventSource?.readyState === EventSource.CLOSED) {
        this.closeTrainingStream();
      }
    };
  }

  closeTrainingStream(): void {
    if (this.trainingEventSource) {
      this.trainingEventSource.close();
      this.trainingEventSource = null;
    }
  }

  watchTrainingJob(job: TrainingJob): void {
    this.currentViewedTrainingId = job.training_id;
    if (job.status === TrainingStatus.RUNNING || job.status === TrainingStatus.PENDING) {
      this.subscribeToTrainingProgress(job.training_id);
      this.startLogsAutoRefresh(job.training_id);
    } else {
      this.stopLogsAutoRefresh();
      this.yoloService.getTrainingStatus(job.training_id).subscribe({
        next: (response) => {
          this.currentTrainingProgress = response.progress;
        }
      });
    }
    this.loadTrainingLogs(job.training_id);
    this.trainingRightTab = 'progress';
  }

  loadTrainingLogs(trainingId: string): void {
    this.trainingLogsLoading = true;
    this.yoloService.getTrainingLogs(trainingId).subscribe({
      next: (response) => {
        this.trainingLogs = response.success ? response.epochs : [];
        this.trainingLogsLoading = false;
      },
      error: () => {
        this.trainingLogs = [];
        this.trainingLogsLoading = false;
      }
    });
  }

  refreshProgress(): void {
    if (this.currentViewedTrainingId) {
      this.loadTrainingLogs(this.currentViewedTrainingId);
    }
  }

  startLogsAutoRefresh(trainingId: string): void {
    this.stopLogsAutoRefresh();
    this.logsAutoRefreshing = true;
    this.logsRefreshSub = interval(5000).subscribe(() => {
      this.loadTrainingLogs(trainingId);
    });
  }

  stopLogsAutoRefresh(): void {
    if (this.logsRefreshSub) {
      this.logsRefreshSub.unsubscribe();
      this.logsRefreshSub = null;
    }
    this.logsAutoRefreshing = false;
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

  // ============== Predict ==============

  onPredictImageSelected(event: Event): void {
    const input = event.target as HTMLInputElement;
    if (!input.files || input.files.length === 0) return;

    const file = input.files[0];

    // Create display URL
    if (this.predictImageUrl) {
      URL.revokeObjectURL(this.predictImageUrl);
    }
    this.predictImageUrl = URL.createObjectURL(file);
    this.predictDetections = [];
    this.predictProcessingTime = 0;
    this.predictModelUsed = '';

    // Convert to base64 for API
    this.yoloService.fileToBase64(file).then(base64 => {
      this.predictImage = base64;

      // Pre-load image element for canvas drawing
      const img = new Image();
      img.onload = () => {
        this.predictImageElement = img;
        this.drawPredictCanvas();
      };
      img.src = this.predictImageUrl;
    });
  }

  private loadFromLibrary(projectId: string, pageNumber: number): void {
    this.viewMode = ViewMode.Predict;
    const imageUrl = this.pagesService.getPageImageUrl(projectId, pageNumber);
    this.http.get(imageUrl, { responseType: 'blob' }).subscribe({
      next: (blob) => {
        const file = new File([blob], `page_${pageNumber}.png`, { type: 'image/png' });
        if (this.predictImageUrl) {
          URL.revokeObjectURL(this.predictImageUrl);
        }
        this.predictImageUrl = URL.createObjectURL(file);
        this.predictDetections = [];
        this.predictProcessingTime = 0;
        this.predictModelUsed = '';

        this.yoloService.fileToBase64(file).then(base64 => {
          this.predictImage = base64;
          const img = new Image();
          img.onload = () => {
            this.predictImageElement = img;
            this.drawPredictCanvas();
          };
          img.src = this.predictImageUrl;
        });
      },
      error: () => {
        this.notification.showError('Failed to load image from library');
      }
    });
  }

  browseServerForPredict(): void {
    const dialogRef = this.dialog.open(ImageBrowserDialogComponent, {
      width: '850px', height: '600px'
    });
    dialogRef.afterClosed().subscribe((result: SelectedPage[] | null) => {
      if (!result || result.length === 0) return;
      const page = result[0];
      this.http.get(page.image_url, { responseType: 'blob' }).subscribe(blob => {
        const file = new File([blob], page.filename, { type: 'image/png' });
        // Reuse existing predict image loading logic
        if (this.predictImageUrl) {
          URL.revokeObjectURL(this.predictImageUrl);
        }
        this.predictImageUrl = URL.createObjectURL(file);
        this.predictDetections = [];
        this.predictProcessingTime = 0;
        this.predictModelUsed = '';

        this.yoloService.fileToBase64(file).then(base64 => {
          this.predictImage = base64;
          const img = new Image();
          img.onload = () => {
            this.predictImageElement = img;
            this.drawPredictCanvas();
          };
          img.src = this.predictImageUrl;
        });
      });
    });
  }

  runPrediction(): void {
    if (!this.predictImage) {
      this.notification.showWarning('Please upload an image first');
      return;
    }

    this.isPredicting = true;
    this.yoloService.predict(
      this.predictImage,
      this.predictModel,
      this.predictConfidence,
      this.predictIou
    ).subscribe({
      next: (response) => {
        this.predictDetections = response.detections;
        this.predictProcessingTime = response.processing_time_ms;
        this.predictModelUsed = response.model_used;
        this.isPredicting = false;
        this.drawPredictCanvas();
        this.notification.showSuccess(
          `Detected ${response.detections.length} objects in ${response.processing_time_ms}ms`
        );
      },
      error: (err) => {
        this.isPredicting = false;
        const detail = err.error?.detail || err.message || 'Prediction failed';
        this.notification.showError(detail);
      }
    });
  }

  extractDetections(): void {
    if (!this.predictImageElement || this.predictDetections.length === 0) {
      this.notification.showWarning('No detections to extract');
      return;
    }

    const img = this.predictImageElement;
    this.extractedDetections = [];

    for (let i = 0; i < this.predictDetections.length; i++) {
      const det = this.predictDetections[i];
      if (det.confidence < this.extractMinConfidence) continue;
      const { x, y, width, height } = det.bbox;

      // Crop from the original (unscaled) image
      const offscreen = document.createElement('canvas');
      offscreen.width = Math.round(width);
      offscreen.height = Math.round(height);
      const ctx = offscreen.getContext('2d');
      if (!ctx) continue;

      ctx.drawImage(
        img,
        Math.round(x), Math.round(y), Math.round(width), Math.round(height),
        0, 0, offscreen.width, offscreen.height
      );

      this.extractedDetections.push({
        dataUrl: offscreen.toDataURL('image/png'),
        className: det.class_name,
        confidence: det.confidence,
        index: i
      });
    }

    this.notification.showSuccess(`Extracted ${this.extractedDetections.length} detections`);
  }

  downloadExtraction(crop: { dataUrl: string; className: string; confidence: number; index: number }): void {
    const link = document.createElement('a');
    link.href = crop.dataUrl;
    link.download = `${crop.className}_${crop.index}_${(crop.confidence * 100).toFixed(0)}pct.png`;
    link.click();
  }

  downloadAllExtractions(): void {
    for (const crop of this.extractedDetections) {
      this.downloadExtraction(crop);
    }
  }

  downloadAnnotatedPage(): void {
    if (!this.predictCanvasRef) return;
    const canvas = this.predictCanvasRef.nativeElement;
    const link = document.createElement('a');
    link.href = canvas.toDataURL('image/png');
    link.download = `annotated_page_${Date.now()}.png`;
    link.click();
  }

  async onBatchFilesSelected(event: Event): Promise<void> {
    const input = event.target as HTMLInputElement;
    if (!input.files || input.files.length === 0) return;

    const files = Array.from(input.files);
    this.isBatchProcessing = true;
    this.batchTotal = files.length;
    this.batchProcessed = 0;
    this.batchFailed = 0;
    this.batchTotalDetections = 0;

    const zip = new JSZip();
    let cropIndex = 0;

    for (const file of files) {
      const baseName = file.name.replace(/\.[^.]+$/, '');

      try {
        // Convert to base64
        const base64 = await this.yoloService.fileToBase64(file);

        // Run prediction
        const response = await this.yoloService.predict(
          base64,
          this.predictModel,
          this.predictConfidence,
          this.predictIou
        ).toPromise();

        if (!response || response.detections.length === 0) {
          this.batchProcessed++;
          continue;
        }

        // Load image for cropping
        const img = await this.loadImage(URL.createObjectURL(file));

        // Save the annotated page (image + bboxes overlay) to ZIP
        const annotatedCanvas = this.drawAnnotatedPage(img, response.detections);
        const annotatedBlob = await new Promise<Blob>((resolve) =>
          annotatedCanvas.toBlob((b) => resolve(b!), 'image/png')
        );
        zip.file(`${baseName}/_annotated_page.png`, annotatedBlob);

        // Extract each detection above confidence threshold
        for (const det of response.detections) {
          if (det.confidence < this.extractMinConfidence) continue;

          const { x, y, width, height } = det.bbox;
          const offscreen = document.createElement('canvas');
          offscreen.width = Math.round(width);
          offscreen.height = Math.round(height);
          const ctx = offscreen.getContext('2d');
          if (!ctx) continue;

          ctx.drawImage(
            img,
            Math.round(x), Math.round(y), Math.round(width), Math.round(height),
            0, 0, offscreen.width, offscreen.height
          );

          // Get PNG blob and add to zip
          const blob = await new Promise<Blob>((resolve) =>
            offscreen.toBlob((b) => resolve(b!), 'image/png')
          );

          const fileName = `${baseName}/${det.class_name}_${cropIndex}_${(det.confidence * 100).toFixed(0)}pct.png`;
          zip.file(fileName, blob);
          cropIndex++;
          this.batchTotalDetections++;
        }

        URL.revokeObjectURL(img.src);
      } catch (err) {
        console.error(`Batch prediction failed for ${file.name}`, err);
        this.batchFailed++;
      }

      this.batchProcessed++;
    }

    // Generate and download ZIP
    if (cropIndex > 0) {
      const zipBlob = await zip.generateAsync({ type: 'blob' });
      const link = document.createElement('a');
      link.href = URL.createObjectURL(zipBlob);
      link.download = `detections_${new Date().toISOString().slice(0, 10)}.zip`;
      link.click();
      URL.revokeObjectURL(link.href);
      this.notification.showSuccess(`Downloaded ${cropIndex} detections from ${this.batchProcessed - this.batchFailed} images`);
    } else {
      this.notification.showWarning('No detections found in any image');
    }

    this.isBatchProcessing = false;
    input.value = '';
  }


  private blobToBase64(blob: Blob): Promise<string> {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => {
        const result = reader.result as string;
        resolve(result.split(',')[1]);
      };
      reader.onerror = reject;
      reader.readAsDataURL(blob);
    });
  }

  private loadImage(src: string): Promise<HTMLImageElement> {
    return new Promise((resolve, reject) => {
      const img = new Image();
      img.onload = () => resolve(img);
      img.onerror = reject;
      img.src = src;
    });
  }

  private drawAnnotatedPage(img: HTMLImageElement, detections: Detection[]): HTMLCanvasElement {
    const canvas = document.createElement('canvas');
    canvas.width = img.naturalWidth;
    canvas.height = img.naturalHeight;
    const ctx = canvas.getContext('2d')!;

    ctx.drawImage(img, 0, 0);

    for (const det of detections) {
      const { x, y, width, height } = det.bbox;
      const color = this.getDetectionClassColor(det.class_name);

      ctx.strokeStyle = color;
      ctx.lineWidth = 3;
      ctx.strokeRect(x, y, width, height);

      const label = `${det.class_name} ${(det.confidence * 100).toFixed(0)}%`;
      ctx.font = '16px sans-serif';
      const textWidth = ctx.measureText(label).width;
      ctx.fillStyle = color;
      ctx.fillRect(x, y - 22, textWidth + 8, 22);

      ctx.fillStyle = '#fff';
      ctx.fillText(label, x + 4, y - 5);
    }

    return canvas;
  }

  clearPrediction(): void {
    if (this.predictImageUrl) {
      URL.revokeObjectURL(this.predictImageUrl);
    }
    this.predictImage = null;
    this.predictImageUrl = null;
    this.predictImageElement = null;
    this.predictDetections = [];
    this.extractedDetections = [];
    this.predictProcessingTime = 0;
    this.predictModelUsed = '';
  }

  getDetectionClassColor(className: string): string {
    return getClassColor(className);
  }

  private drawPredictCanvas(): void {
    if (!this.predictCanvasRef || !this.predictImageElement) return;

    const canvas = this.predictCanvasRef.nativeElement;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const img = this.predictImageElement;

    // Scale to fit container (max 800px wide)
    const maxWidth = 800;
    const scale = img.naturalWidth > maxWidth ? maxWidth / img.naturalWidth : 1;
    canvas.width = img.naturalWidth * scale;
    canvas.height = img.naturalHeight * scale;

    // Draw image
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height);

    // Draw detections
    for (const det of this.predictDetections) {
      const x = det.bbox.x * scale;
      const y = det.bbox.y * scale;
      const w = det.bbox.width * scale;
      const h = det.bbox.height * scale;
      const color = this.getDetectionClassColor(det.class_name);

      // Draw box
      ctx.strokeStyle = color;
      ctx.lineWidth = 2;
      ctx.strokeRect(x, y, w, h);

      // Draw label background
      const label = `${det.class_name} ${(det.confidence * 100).toFixed(0)}%`;
      ctx.font = '13px sans-serif';
      const textWidth = ctx.measureText(label).width;
      ctx.fillStyle = color;
      ctx.fillRect(x, y - 18, textWidth + 6, 18);

      // Draw label text
      ctx.fillStyle = '#fff';
      ctx.fillText(label, x + 3, y - 4);
    }
  }

  // ============== Sidebar Stats ==============

  getTotalImages(): number {
    return this.datasets.reduce((sum, ds) => sum + ds.image_count, 0);
  }

  getTotalAnnotations(): number {
    return this.selectedDataset ? this.selectedDataset.total_annotations : 0;
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

  // ============== Auto-Annotate ==============

  showAutoAnnotateForm(): void {
    this.autoAnnotateFormVisible = true;
    this.autoAnnotateProjectId = '';
    this.autoAnnotateProjectName = '';
    this.autoAnnotateModel = '';
    this.autoAnnotateDatasetName = '';
    this.autoAnnotateConfidence = 0.25;
    this.autoAnnotateStatus = null;
    this.autoAnnotateJobId = null;
  }

  hideAutoAnnotateForm(): void {
    this.autoAnnotateFormVisible = false;
    this.stopAutoAnnotatePoll();
  }

  browseProjectForAutoAnnotate(): void {
    const dialogRef = this.dialog.open(ImageBrowserDialogComponent, {
      width: '850px', height: '600px'
    });
    dialogRef.afterClosed().subscribe((result: SelectedPage[] | null) => {
      if (!result || result.length === 0) return;
      const page = result[0];
      this.autoAnnotateProjectId = page.project_id;
      this.autoAnnotateProjectName = page.project_name;
      if (!this.autoAnnotateDatasetName) {
        this.autoAnnotateDatasetName = page.project_name.replace(/\s+/g, '_') + '_auto';
      }
    });
  }

  startAutoAnnotate(): void {
    if (!this.autoAnnotateProjectId) {
      this.notification.showWarning('Please select a source project');
      return;
    }
    if (!this.autoAnnotateModel) {
      this.notification.showWarning('Please select a model');
      return;
    }
    if (!this.autoAnnotateDatasetName.trim()) {
      this.notification.showWarning('Please enter a dataset name');
      return;
    }

    this.isAutoAnnotating = true;
    this.yoloService.startAutoAnnotate({
      source_project_id: this.autoAnnotateProjectId,
      model_name: this.autoAnnotateModel,
      dataset_name: this.autoAnnotateDatasetName.trim(),
      confidence: this.autoAnnotateConfidence,
      iou: this.autoAnnotateIou,
      val_ratio: this.autoAnnotateValRatio,
    }).subscribe({
      next: (response) => {
        if (response.success) {
          this.autoAnnotateJobId = response.job_id;
          this.notification.showSuccess(`Auto-annotation started: ${response.total_images} images`);
          this.startAutoAnnotatePoll(response.job_id);
        } else {
          this.notification.showError(response.message);
          this.isAutoAnnotating = false;
        }
      },
      error: (err) => {
        const detail = err.error?.detail || err.message || 'Failed to start auto-annotation';
        this.notification.showError(detail);
        this.isAutoAnnotating = false;
      }
    });
  }

  private startAutoAnnotatePoll(jobId: string): void {
    this.stopAutoAnnotatePoll();
    this.autoAnnotatePollSub = interval(1500)
      .pipe(
        takeUntil(this.destroy$),
        switchMap(() => this.yoloService.getAutoAnnotateStatus(jobId))
      )
      .subscribe({
        next: (status) => {
          this.autoAnnotateStatus = status;
          if (status.status === 'completed') {
            this.isAutoAnnotating = false;
            this.stopAutoAnnotatePoll();
            this.notification.showSuccess(
              `Auto-annotation complete: ${status.total_detections} detections across ${status.total_images} images`
            );
            this.loadDashboardData();
          } else if (status.status === 'failed') {
            this.isAutoAnnotating = false;
            this.stopAutoAnnotatePoll();
            this.notification.showError(`Auto-annotation failed: ${status.error}`);
          }
        },
        error: () => {
          this.stopAutoAnnotatePoll();
          this.isAutoAnnotating = false;
        }
      });
  }

  private stopAutoAnnotatePoll(): void {
    if (this.autoAnnotatePollSub) {
      this.autoAnnotatePollSub.unsubscribe();
      this.autoAnnotatePollSub = null;
    }
  }

  openAutoAnnotatedDataset(): void {
    if (!this.autoAnnotateStatus) return;
    const datasetName = this.autoAnnotateStatus.dataset_name;
    this.yoloService.getDatasetStats(datasetName).subscribe({
      next: (stats) => {
        this.selectedDataset = stats;
        this.openAnnotation(stats);
        this.autoAnnotateFormVisible = false;
      },
      error: () => {
        this.notification.showError('Failed to load auto-annotated dataset');
      }
    });
  }
}

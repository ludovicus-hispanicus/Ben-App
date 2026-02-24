import { Component, OnInit, OnDestroy } from '@angular/core';
import { VlmOcrService, VlmOcrProcessResponse } from 'src/app/services/vlm-ocr.service';
import { CloudOcrService, CloudProvider, CloudOcrProvider, CloudOcrModel, CLOUD_PROVIDERS } from 'src/app/services/cloud-ocr.service';
import { NotificationService } from 'src/app/services/notification.service';
import { ToolbarService } from 'src/app/services/toolbar.service';
import { saveAs } from 'file-saver';

type SourceType = 'ahw' | 'cad' | 'generic';
type OcrProvider = 'local' | CloudProvider;

@Component({
  selector: 'app-dictionary-ocr',
  templateUrl: './dictionary-ocr.component.html',
  styleUrls: ['./dictionary-ocr.component.scss']
})
export class DictionaryOcrComponent implements OnInit, OnDestroy {
  // State
  isLoading = false;
  isDragOver = false;
  vlmAvailable: boolean | null = null;

  // File handling
  selectedFile: File | null = null;
  imagePreview: string | null = null;
  isPdf = false;
  currentPage = 0;
  totalPages = 0;

  // OCR Settings
  sourceType: SourceType = 'ahw';
  sourceTypes: { value: SourceType; label: string }[] = [
    { value: 'ahw', label: 'AHw (Akkadisches Handwörterbuch)' },
    { value: 'cad', label: 'CAD (Chicago Assyrian Dictionary)' },
    { value: 'generic', label: 'Generic Document' }
  ];

  // Model picker
  selectedProvider: OcrProvider = 'local';
  selectedModel: string = 'deepseek-ocr';
  cloudProviders = CLOUD_PROVIDERS;
  apiKeys: { [provider: string]: string } = {};
  showApiKey = false;

  // Results
  ocrResult: string = '';
  originalResult: string = '';
  processingTimeMs: number = 0;
  hasChanges = false;
  imageId: string = '';

  // Edit mode
  isEditing = false;

  constructor(
    private vlmOcrService: VlmOcrService,
    private cloudOcrService: CloudOcrService,
    private notificationService: NotificationService,
    private toolbarService: ToolbarService
  ) {}

  ngOnInit(): void {
    this.checkVlmHealth();
    this.loadApiKeys();
    this.updateToolbar();
  }

  ngOnDestroy(): void {
    this.toolbarService.clearButtons();
  }

  // ============== Model Picker ==============

  get currentCloudProvider(): CloudOcrProvider | null {
    if (this.selectedProvider === 'local') return null;
    return this.cloudProviders.find(p => p.id === this.selectedProvider) || null;
  }

  get currentModels(): CloudOcrModel[] {
    return this.currentCloudProvider?.models || [];
  }

  get currentApiKey(): string {
    return this.apiKeys[this.selectedProvider] || '';
  }

  get canProcess(): boolean {
    if (!this.selectedFile) return false;
    if (this.isLoading) return false;
    if (this.selectedProvider === 'local') return this.vlmAvailable !== false;
    return !!this.currentApiKey;
  }

  get processButtonLabel(): string {
    if (this.isLoading) return 'Processing...';
    if (this.selectedProvider === 'local') return 'Process with DeepSeek-OCR';
    const model = this.currentModels.find(m => m.id === this.selectedModel);
    return model ? `Process with ${model.label}` : 'Process';
  }

  onProviderChange(): void {
    if (this.selectedProvider === 'local') {
      this.selectedModel = 'deepseek-ocr';
    } else {
      const models = this.currentModels;
      this.selectedModel = models.length > 0 ? models[0].id : '';
    }
    this.showApiKey = false;
  }

  onApiKeyChange(value: string): void {
    this.apiKeys[this.selectedProvider] = value;
    this.cloudOcrService.saveApiKeys(this.apiKeys);
  }

  private loadApiKeys(): void {
    this.apiKeys = this.cloudOcrService.loadApiKeys();
  }

  // ============== Health Check ==============

  checkVlmHealth(): void {
    this.vlmOcrService.checkHealth().subscribe({
      next: (response) => {
        this.vlmAvailable = response.vlm_service_available;
        if (!this.vlmAvailable) {
          this.notificationService.showWarning(
            'Local DeepSeek-OCR is not available. Use a cloud API model instead.',
            10000
          );
        }
      },
      error: () => {
        this.vlmAvailable = false;
      }
    });
  }

  updateToolbar(): void {
    const buttons = [];

    if (this.ocrResult) {
      buttons.push({
        label: 'Export TXT',
        icon: 'download',
        action: () => this.exportResult(),
        color: 'default'
      });

      if (this.hasChanges) {
        buttons.push({
          label: 'Save Correction',
          icon: 'check_circle',
          action: () => this.saveCorrection(),
          color: 'primary'
        });
      }

      buttons.push({
        label: 'Clear',
        icon: 'refresh',
        action: () => this.clearAll(),
        color: 'warn'
      });
    }

    this.toolbarService.setToolbar({
      buttons,
      message: this.isLoading ? `Processing with ${this.selectedModel}...` : undefined
    });
  }

  // Drag and drop handlers
  onDragOver(event: DragEvent): void {
    event.preventDefault();
    event.stopPropagation();
    this.isDragOver = true;
  }

  onDragLeave(event: DragEvent): void {
    event.preventDefault();
    event.stopPropagation();
    this.isDragOver = false;
  }

  onDrop(event: DragEvent): void {
    event.preventDefault();
    event.stopPropagation();
    this.isDragOver = false;

    const files = event.dataTransfer?.files;
    if (files && files.length > 0) {
      this.handleFile(files[0]);
    }
  }

  onFileSelect(event: Event): void {
    const input = event.target as HTMLInputElement;
    if (input.files && input.files.length > 0) {
      this.handleFile(input.files[0]);
    }
  }

  handleFile(file: File): void {
    const validTypes = ['image/png', 'image/jpeg', 'image/jpg', 'application/pdf'];

    if (!validTypes.includes(file.type)) {
      this.notificationService.showError('Please upload a PNG, JPG, or PDF file.');
      return;
    }

    const maxSize = 20 * 1024 * 1024; // 20MB
    if (file.size > maxSize) {
      this.notificationService.showError('File is too large. Maximum size is 20MB.');
      return;
    }

    this.selectedFile = file;
    this.isPdf = file.type === 'application/pdf';
    this.imageId = `${this.sourceType}_${Date.now()}`;

    if (this.isPdf) {
      this.imagePreview = null;
      this.currentPage = 0;
    } else {
      const reader = new FileReader();
      reader.onload = (e) => {
        this.imagePreview = e.target?.result as string;
      };
      reader.readAsDataURL(file);
    }
  }

  processOcr(): void {
    if (!this.selectedFile) {
      this.notificationService.showError('Please select a file first.');
      return;
    }

    if (this.selectedProvider !== 'local' && !this.currentApiKey) {
      this.notificationService.showError('Please enter an API key for the selected provider.');
      return;
    }

    this.isLoading = true;
    this.toolbarService.setLoading(true);
    this.updateToolbar();

    if (this.selectedProvider === 'local') {
      // Use existing DeepSeek-OCR flow
      if (this.isPdf) {
        this.processPdfLocal();
      } else {
        this.processImageLocal();
      }
    } else {
      // Use cloud API
      this.processImageCloud();
    }
  }

  private processImageLocal(): void {
    if (!this.imagePreview) return;

    const base64Data = this.imagePreview.includes(',')
      ? this.imagePreview.split(',')[1]
      : this.imagePreview;

    this.vlmOcrService.processImage(base64Data, this.sourceType).subscribe({
      next: (response) => this.handleOcrResponse(response),
      error: (error) => this.handleOcrError(error)
    });
  }

  private processPdfLocal(): void {
    if (!this.selectedFile) return;

    this.vlmOcrService.processPdf(this.selectedFile, this.currentPage, this.sourceType).subscribe({
      next: (response) => this.handleOcrResponse(response),
      error: (error) => this.handleOcrError(error)
    });
  }

  private processImageCloud(): void {
    // For cloud APIs, we need the base64 image data
    if (this.isPdf) {
      this.notificationService.showWarning('PDF processing is only supported with local DeepSeek-OCR for now.');
      this.isLoading = false;
      this.toolbarService.setLoading(false);
      this.updateToolbar();
      return;
    }

    if (!this.imagePreview) return;

    const base64Data = this.imagePreview.includes(',')
      ? this.imagePreview.split(',')[1]
      : this.imagePreview;

    this.cloudOcrService.processImage(
      base64Data,
      this.selectedProvider as CloudProvider,
      this.selectedModel,
      this.currentApiKey,
      this.sourceType
    ).subscribe({
      next: (response) => this.handleOcrResponse(response),
      error: (error) => this.handleOcrError(error)
    });
  }

  private handleOcrResponse(response: VlmOcrProcessResponse): void {
    this.isLoading = false;
    this.toolbarService.setLoading(false);

    if (response.success) {
      this.ocrResult = response.text;
      this.originalResult = response.text;
      this.processingTimeMs = response.processing_time_ms;
      this.hasChanges = false;
      this.notificationService.showSuccess(
        `OCR completed in ${(response.processing_time_ms / 1000).toFixed(1)}s${response.model ? ' (' + response.model + ')' : ''}`
      );
    } else {
      this.notificationService.showError(response.error || 'OCR processing failed.');
    }

    this.updateToolbar();
  }

  private handleOcrError(error: any): void {
    this.isLoading = false;
    this.toolbarService.setLoading(false);
    this.notificationService.showError('Failed to process image. Please try again.');
    console.error('OCR error:', error);
    this.updateToolbar();
  }

  onTextChange(): void {
    this.hasChanges = this.ocrResult !== this.originalResult;
    this.updateToolbar();
  }

  toggleEdit(): void {
    this.isEditing = !this.isEditing;
  }

  exportResult(): void {
    if (!this.ocrResult) return;

    const header = `Dictionary OCR Result - ${this.sourceType.toUpperCase()}\n`;
    const timestamp = `Generated: ${new Date().toISOString()}\n`;
    const separator = '='.repeat(50) + '\n\n';

    const content = header + timestamp + separator + this.ocrResult;

    const blob = new Blob([content], { type: 'text/plain;charset=utf-8' });
    const filename = `${this.sourceType}-ocr-${Date.now()}.txt`;
    saveAs(blob, filename);

    this.notificationService.showSuccess('Result exported successfully!');
  }

  saveCorrection(): void {
    if (!this.hasChanges || !this.ocrResult) return;

    this.vlmOcrService.saveCorrection(
      this.imageId,
      this.originalResult,
      this.ocrResult,
      this.sourceType
    ).subscribe({
      next: (response) => {
        if (response.success) {
          this.notificationService.showSuccess(response.message);
          this.originalResult = this.ocrResult;
          this.hasChanges = false;
          this.updateToolbar();
        }
      },
      error: () => {
        this.notificationService.showError('Failed to save correction.');
      }
    });
  }

  copyToClipboard(): void {
    if (!this.ocrResult) return;

    navigator.clipboard.writeText(this.ocrResult).then(() => {
      this.notificationService.showSuccess('Copied to clipboard!');
    });
  }

  clearAll(): void {
    if (this.hasChanges && !confirm('You have unsaved changes. Are you sure you want to clear?')) {
      return;
    }

    this.selectedFile = null;
    this.imagePreview = null;
    this.isPdf = false;
    this.currentPage = 0;
    this.ocrResult = '';
    this.originalResult = '';
    this.hasChanges = false;
    this.processingTimeMs = 0;
    this.isEditing = false;
    this.updateToolbar();
  }

  previousPage(): void {
    if (this.currentPage > 0) {
      this.currentPage--;
    }
  }

  nextPage(): void {
    this.currentPage++;
  }
}

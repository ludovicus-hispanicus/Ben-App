import { Component, OnInit, OnDestroy } from '@angular/core';
import { VlmOcrService, VlmOcrProcessResponse } from 'src/app/services/vlm-ocr.service';
import { NotificationService } from 'src/app/services/notification.service';
import { ToolbarService } from 'src/app/services/toolbar.service';
import { saveAs } from 'file-saver';

type SourceType = 'ahw' | 'cad' | 'generic';

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
    private notificationService: NotificationService,
    private toolbarService: ToolbarService
  ) {}

  ngOnInit(): void {
    this.checkVlmHealth();
    this.updateToolbar();
  }

  ngOnDestroy(): void {
    this.toolbarService.clearButtons();
  }

  checkVlmHealth(): void {
    this.vlmOcrService.checkHealth().subscribe({
      next: (response) => {
        this.vlmAvailable = response.vlm_service_available;
        if (!this.vlmAvailable) {
          this.notificationService.showWarning(
            'VLM OCR service is not available. Please ensure the vlm-ocr container is running.',
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
      message: this.isLoading ? 'Processing with DeepSeek-OCR...' : undefined
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
      // For PDF, we'll process on button click
      this.imagePreview = null;
      this.currentPage = 0;
      // TODO: Add PDF page count detection
    } else {
      // For images, show preview
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

    this.isLoading = true;
    this.toolbarService.setLoading(true);
    this.updateToolbar();

    if (this.isPdf) {
      this.processPdf();
    } else {
      this.processImage();
    }
  }

  private processImage(): void {
    if (!this.imagePreview) return;

    // Extract base64 data (remove data:image/xxx;base64, prefix)
    const base64Data = this.imagePreview.includes(',')
      ? this.imagePreview.split(',')[1]
      : this.imagePreview;

    this.vlmOcrService.processImage(base64Data, this.sourceType).subscribe({
      next: (response) => this.handleOcrResponse(response),
      error: (error) => this.handleOcrError(error)
    });
  }

  private processPdf(): void {
    if (!this.selectedFile) return;

    this.vlmOcrService.processPdf(this.selectedFile, this.currentPage, this.sourceType).subscribe({
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
        `OCR completed in ${(response.processing_time_ms / 1000).toFixed(1)}s`
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

  // PDF navigation (for future implementation)
  previousPage(): void {
    if (this.currentPage > 0) {
      this.currentPage--;
    }
  }

  nextPage(): void {
    this.currentPage++;
  }
}

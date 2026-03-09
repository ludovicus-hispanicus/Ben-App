import { Component, Inject } from '@angular/core';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';

export interface PageRangeDialogData {
  filename: string;
  pageCount: number;
}

export interface PageRangeDialogResult {
  pageFrom: number | null;
  pageTo: number | null;
  dpi: number | null;
}

@Component({
  selector: 'app-page-range-dialog',
  templateUrl: './page-range-dialog.component.html',
  styleUrls: ['./page-range-dialog.component.scss']
})
export class PageRangeDialogComponent {
  pageFrom: number | null = null;
  pageTo: number | null = null;
  dpi = 300;

  dpiOptions = [
    { value: 72, label: '72 DPI (fast, low quality)' },
    { value: 150, label: '150 DPI' },
    { value: 200, label: '200 DPI' },
    { value: 300, label: '300 DPI (default)' },
    { value: 400, label: '400 DPI' },
    { value: 600, label: '600 DPI (very high)' }
  ];

  constructor(
    public dialogRef: MatDialogRef<PageRangeDialogComponent>,
    @Inject(MAT_DIALOG_DATA) public data: PageRangeDialogData
  ) {}

  get extractCount(): number {
    const from = this.pageFrom || 1;
    const to = this.pageTo || this.data.pageCount;
    return Math.max(0, to - from + 1);
  }

  onCancel(): void {
    this.dialogRef.close(null);
  }

  onExtractAll(): void {
    this.dialogRef.close({ pageFrom: null, pageTo: null, dpi: this.dpi } as PageRangeDialogResult);
  }

  onExtractRange(): void {
    this.dialogRef.close({
      pageFrom: this.pageFrom || null,
      pageTo: this.pageTo || null,
      dpi: this.dpi
    } as PageRangeDialogResult);
  }
}

import { Component, Inject } from '@angular/core';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';
import { DatasetPreview } from '../../../models/cured';

export interface MoveTextDialogData {
  datasets: DatasetPreview[];
  currentDatasetId: number | null;
  selectedCount: number;  // how many texts are currently selected
}

export interface MoveTextDialogResult {
  datasetId: number | null;
  moveAll: boolean;  // true = move all selected, false = move only the clicked one
}

@Component({
  selector: 'app-move-text-dialog',
  templateUrl: './move-text-dialog.component.html',
  styleUrls: ['./move-text-dialog.component.scss']
})
export class MoveTextDialogComponent {
  selectedDatasetId: number | null = null;
  moveAll = false;

  constructor(
    public dialogRef: MatDialogRef<MoveTextDialogComponent>,
    @Inject(MAT_DIALOG_DATA) public data: MoveTextDialogData
  ) {
    this.selectedDatasetId = data.currentDatasetId;
  }

  get availableDatasets(): DatasetPreview[] {
    return this.data.datasets.filter(p => p.dataset_id !== this.data.currentDatasetId);
  }

  get hasMultipleSelected(): boolean {
    return this.data.selectedCount > 1;
  }

  onCancel(): void {
    this.dialogRef.close(undefined);
  }

  onMove(): void {
    this.dialogRef.close({ datasetId: this.selectedDatasetId, moveAll: this.moveAll } as MoveTextDialogResult);
  }
}

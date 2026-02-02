import { Component, Inject } from '@angular/core';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';

export interface LabelDialogData {
  currentLabel: string;
  existingLabels: string[];
}

@Component({
  selector: 'app-label-dialog',
  templateUrl: './label-dialog.component.html',
  styleUrls: ['./label-dialog.component.scss']
})
export class LabelDialogComponent {
  labelInput: string = '';

  constructor(
    public dialogRef: MatDialogRef<LabelDialogComponent>,
    @Inject(MAT_DIALOG_DATA) public data: LabelDialogData
  ) {
    this.labelInput = data.currentLabel || '';
  }

  selectLabel(label: string): void {
    this.labelInput = label;
  }

  clearLabel(): void {
    this.labelInput = '';
  }

  onCancel(): void {
    this.dialogRef.close(null);
  }

  onSave(): void {
    this.dialogRef.close(this.labelInput.trim());
  }
}

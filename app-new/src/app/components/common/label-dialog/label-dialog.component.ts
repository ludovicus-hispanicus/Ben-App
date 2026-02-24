import { Component, Inject } from '@angular/core';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';

export interface LabelDialogData {
  currentLabel?: string;
  currentLabels?: string[];
  existingLabels: string[];
}

@Component({
  selector: 'app-label-dialog',
  templateUrl: './label-dialog.component.html',
  styleUrls: ['./label-dialog.component.scss']
})
export class LabelDialogComponent {
  labelInput: string = '';
  selectedLabels: string[] = [];

  constructor(
    public dialogRef: MatDialogRef<LabelDialogComponent>,
    @Inject(MAT_DIALOG_DATA) public data: LabelDialogData
  ) {
    const initial = data.currentLabels && data.currentLabels.length > 0
      ? data.currentLabels
      : (data.currentLabel ? [data.currentLabel] : []);
    this.selectedLabels = [...initial];
  }

  isSelected(label: string): boolean {
    return this.selectedLabels.includes(label);
  }

  toggleLabel(label: string): void {
    const idx = this.selectedLabels.indexOf(label);
    if (idx >= 0) {
      this.selectedLabels.splice(idx, 1);
    } else {
      this.selectedLabels.push(label);
    }
  }

  addCustomLabel(): void {
    const trimmed = this.labelInput.trim();
    if (trimmed && !this.selectedLabels.includes(trimmed)) {
      this.selectedLabels.push(trimmed);
    }
    if (trimmed) {
      this.labelInput = '';
    }
  }

  removeLabel(label: string): void {
    const idx = this.selectedLabels.indexOf(label);
    if (idx >= 0) {
      this.selectedLabels.splice(idx, 1);
    }
  }

  clearLabels(): void {
    this.selectedLabels = [];
  }

  onCancel(): void {
    this.dialogRef.close(null);
  }

  onSave(): void {
    // Auto-add any pending input so user doesn't lose typed labels
    const trimmed = this.labelInput.trim();
    if (trimmed && !this.selectedLabels.includes(trimmed)) {
      this.selectedLabels.push(trimmed);
    }
    this.dialogRef.close([...this.selectedLabels]);
  }
}

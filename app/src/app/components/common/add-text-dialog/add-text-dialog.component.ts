import { Component, Inject } from '@angular/core';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';

export interface AddTextDialogData {
  identifier: string;
  identifierType: string;
  existingLabels: string[];
}

export interface AddTextDialogResult {
  source: 'local' | 'server';
  useOcr: boolean;
  label: string;
}

@Component({
  selector: 'app-add-text-dialog',
  templateUrl: './add-text-dialog.component.html',
  styleUrls: ['./add-text-dialog.component.scss']
})
export class AddTextDialogComponent {
  source: 'local' | 'server' = 'local';
  useOcr: boolean = true;
  label: string = '';

  constructor(
    public dialogRef: MatDialogRef<AddTextDialogComponent>,
    @Inject(MAT_DIALOG_DATA) public data: AddTextDialogData
  ) {}

  pickExisting(label: string): void {
    this.label = label;
  }

  isValid(): boolean {
    return !!this.label.trim();
  }

  onCancel(): void {
    this.dialogRef.close(null);
  }

  onConfirm(): void {
    if (!this.isValid()) return;
    this.dialogRef.close({
      source: this.source,
      useOcr: this.useOcr,
      label: this.label.trim()
    });
  }
}

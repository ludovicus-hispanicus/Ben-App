import { Component, Inject } from '@angular/core';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';
import { FormControl } from '@angular/forms';

export interface PartDialogData {
  currentPart: string;
}

export interface PartDialogResult {
  part: string;
}

@Component({
  selector: 'app-part-dialog',
  templateUrl: './part-dialog.component.html',
  styleUrls: ['./part-dialog.component.scss']
})
export class PartDialogComponent {
  partControl = new FormControl('');

  constructor(
    public dialogRef: MatDialogRef<PartDialogComponent>,
    @Inject(MAT_DIALOG_DATA) public data: PartDialogData
  ) {
    this.partControl.setValue(data.currentPart || '');
  }

  onCancel(): void {
    this.dialogRef.close(null);
  }

  onSave(): void {
    const result: PartDialogResult = {
      part: String(this.partControl.value || '').trim()
    };
    this.dialogRef.close(result);
  }
}

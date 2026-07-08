import { Component, Inject } from '@angular/core';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';

export interface PromptDialogData {
  title: string;
  message: string;
  value?: string;
  placeholder?: string;
  confirmText?: string;
  cancelText?: string;
  required?: boolean;
}

@Component({
  selector: 'app-prompt-dialog',
  templateUrl: './prompt-dialog.component.html',
  styleUrls: ['./prompt-dialog.component.scss']
})
export class PromptDialogComponent {
  value: string;

  constructor(
    public dialogRef: MatDialogRef<PromptDialogComponent>,
    @Inject(MAT_DIALOG_DATA) public data: PromptDialogData
  ) {
    this.value = data.value || '';
    if (!data.confirmText) { data.confirmText = 'OK'; }
    if (!data.cancelText) { data.cancelText = 'Cancel'; }
  }

  isValid(): boolean {
    return !this.data.required || !!this.value.trim();
  }

  onCancel(): void {
    // null signals "cancelled" — distinct from an empty-string result.
    this.dialogRef.close(null);
  }

  onConfirm(): void {
    if (!this.isValid()) return;
    this.dialogRef.close(this.value.trim());
  }
}

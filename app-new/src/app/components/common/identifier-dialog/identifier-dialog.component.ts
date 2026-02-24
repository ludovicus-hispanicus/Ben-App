import { Component, Inject } from '@angular/core';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';
import { FormControl } from '@angular/forms';

export interface IdentifierDialogData {
  museumNumber: string;
  pNumber: string;
  publicationNumber: string;
}

export interface IdentifierDialogResult {
  museumNumber: string;
  pNumber: string;
  publicationNumber: string;
}

@Component({
  selector: 'app-identifier-dialog',
  templateUrl: './identifier-dialog.component.html',
  styleUrls: ['./identifier-dialog.component.scss']
})
export class IdentifierDialogComponent {
  museumNumberControl = new FormControl('');
  pNumberControl = new FormControl('');
  publicationNumberControl = new FormControl('');

  constructor(
    public dialogRef: MatDialogRef<IdentifierDialogComponent>,
    @Inject(MAT_DIALOG_DATA) public data: IdentifierDialogData
  ) {
    this.museumNumberControl.setValue(data.museumNumber || '');
    this.pNumberControl.setValue(data.pNumber || '');
    this.publicationNumberControl.setValue(data.publicationNumber || '');
  }

  onCancel(): void {
    this.dialogRef.close(null);
  }

  onSave(): void {
    const result: IdentifierDialogResult = {
      museumNumber: String(this.museumNumberControl.value || '').trim(),
      pNumber: String(this.pNumberControl.value || '').trim(),
      publicationNumber: String(this.publicationNumberControl.value || '').trim()
    };
    this.dialogRef.close(result);
  }
}

import { Component, Inject, OnInit } from '@angular/core';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';
import { FormControl } from '@angular/forms';
import { Observable } from 'rxjs';
import { map, startWith } from 'rxjs/operators';

export interface SaveDialogData {
  textId: number | null;
  existingLabels: string[];
  existingParts: number[];
  currentLabel: string;
  currentPart: string;
  museumNumber: string;
  pNumber: string;
  publicationNumber: string;
}

export interface SaveDialogResult {
  museumNumber: string;
  pNumber: string;
  publicationNumber: string;
  label: string;
  part: string;
}

@Component({
  selector: 'app-save-dialog',
  templateUrl: './save-dialog.component.html',
  styleUrls: ['./save-dialog.component.scss']
})
export class SaveDialogComponent implements OnInit {
  museumNumberControl = new FormControl('');
  pNumberControl = new FormControl('');
  publicationNumberControl = new FormControl('');
  labelControl = new FormControl('');
  partInput: number | null = null;
  filteredLabels: Observable<string[]>;

  constructor(
    public dialogRef: MatDialogRef<SaveDialogComponent>,
    @Inject(MAT_DIALOG_DATA) public data: SaveDialogData
  ) {
    // Set current part — extract number from any format ("Part-1", "3", etc.)
    if (data.currentPart) {
      const match = data.currentPart.match(/(\d+)/);
      this.partInput = match ? parseInt(match[1], 10) : null;
    }

    if (data.currentLabel) {
      this.labelControl.setValue(data.currentLabel);
    }
    this.museumNumberControl.setValue(data.museumNumber || '');
    this.pNumberControl.setValue(data.pNumber || '');
    this.publicationNumberControl.setValue(data.publicationNumber || '');
  }

  ngOnInit() {
    this.filteredLabels = this.labelControl.valueChanges.pipe(
      startWith(this.data.currentLabel || ''),
      map(value => this._filterLabels(value || ''))
    );
  }

  private _filterLabels(value: string): string[] {
    const filterValue = value.toLowerCase();
    return this.data.existingLabels.filter(label =>
      label.toLowerCase().includes(filterValue)
    );
  }

  onCancel(): void {
    this.dialogRef.close(null);
  }

  onSave(): void {
    const result: SaveDialogResult = {
      museumNumber: String(this.museumNumberControl.value || '').trim(),
      pNumber: String(this.pNumberControl.value || '').trim(),
      publicationNumber: String(this.publicationNumberControl.value || '').trim(),
      label: String(this.labelControl.value || '').trim(),
      part: this.partInput != null ? String(this.partInput) : ''
    };
    this.dialogRef.close(result);
  }
}

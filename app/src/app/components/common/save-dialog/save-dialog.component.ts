import { Component, Inject, OnInit } from '@angular/core';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';
import { FormControl } from '@angular/forms';
import { Observable } from 'rxjs';
import { map, startWith } from 'rxjs/operators';

export interface SaveDialogData {
  textId: number | null;
  existingLabels: string[];
  currentLabel: string;
  currentPart: string;
}

export interface SaveDialogResult {
  museumNumber: string;
  pNumber: string;
  publicationNumber: string;
  label: string;
  part: string;
}

type LabelSource = 'museum' | 'pnumber' | 'publication' | 'other' | null;

@Component({
  selector: 'app-save-dialog',
  templateUrl: './save-dialog.component.html',
  styleUrls: ['./save-dialog.component.scss']
})
export class SaveDialogComponent implements OnInit {
  museumNumberControl = new FormControl('');
  pNumberControl = new FormControl('');
  publicationNumberControl = new FormControl('');
  otherLabelControl = new FormControl('');
  partInput: string = '';
  filteredLabels: Observable<string[]>;

  // Track which field is being used as label
  activeLabel: LabelSource = null;

  constructor(
    public dialogRef: MatDialogRef<SaveDialogComponent>,
    @Inject(MAT_DIALOG_DATA) public data: SaveDialogData
  ) {
    this.partInput = data.currentPart || '';
    // If there's a current label, put it in the "other" field
    if (data.currentLabel) {
      this.otherLabelControl.setValue(data.currentLabel);
      this.activeLabel = 'other';
    }
  }

  ngOnInit() {
    // Autocomplete for other label field
    this.filteredLabels = this.otherLabelControl.valueChanges.pipe(
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

  useAsLabel(source: LabelSource): void {
    // Toggle: if already active, deactivate
    if (this.activeLabel === source) {
      this.activeLabel = null;
      return;
    }
    this.activeLabel = source;
  }

  private getLabelValue(): string {
    switch (this.activeLabel) {
      case 'museum':
        return String(this.museumNumberControl.value || '').trim();
      case 'pnumber':
        return String(this.pNumberControl.value || '').trim();
      case 'publication':
        return String(this.publicationNumberControl.value || '').trim();
      case 'other':
        return String(this.otherLabelControl.value || '').trim();
      default:
        return '';
    }
  }

  onCancel(): void {
    this.dialogRef.close(null);
  }

  onSave(): void {
    const result: SaveDialogResult = {
      museumNumber: String(this.museumNumberControl.value || '').trim(),
      pNumber: String(this.pNumberControl.value || '').trim(),
      publicationNumber: String(this.publicationNumberControl.value || '').trim(),
      label: this.getLabelValue(),
      part: this.partInput.trim()
    };
    this.dialogRef.close(result);
  }
}

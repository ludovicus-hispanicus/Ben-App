import { Component, Inject, OnInit, OnDestroy } from '@angular/core';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';
import { FormControl } from '@angular/forms';
import { Observable, Subject, merge } from 'rxjs';
import { map, startWith, debounceTime, distinctUntilChanged, switchMap, takeUntil } from 'rxjs/operators';
import { TextService } from '../../../services/text.service';

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
export class SaveDialogComponent implements OnInit, OnDestroy {
  autocompleteOpen = false;
  private autoClosedAt = 0;
  museumNumberControl = new FormControl('');
  pNumberControl = new FormControl('');
  publicationNumberControl = new FormControl('');
  labelControl = new FormControl('');
  partInput: number | null = null;
  filteredLabels: Observable<string[]>;
  private destroy$ = new Subject<void>();

  constructor(
    public dialogRef: MatDialogRef<SaveDialogComponent>,
    @Inject(MAT_DIALOG_DATA) public data: SaveDialogData,
    private textService: TextService
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

    // Debounce identifier changes and look up existing parts
    merge(
      this.museumNumberControl.valueChanges,
      this.pNumberControl.valueChanges,
      this.publicationNumberControl.valueChanges
    ).pipe(
      debounceTime(300),
      map(() => this._getFirstNonEmptyIdentifier()),
      distinctUntilChanged(),
      switchMap(identifier => {
        if (!identifier) {
          return [[]];
        }
        return this.textService.getPartsByIdentifier(identifier);
      }),
      takeUntil(this.destroy$)
    ).subscribe(parts => {
      this.data.existingParts = parts;
    });

    // Also trigger an initial lookup if identifiers are pre-filled
    const initial = this._getFirstNonEmptyIdentifier();
    if (initial) {
      this.textService.getPartsByIdentifier(initial).subscribe(parts => {
        this.data.existingParts = parts;
      });
    }
  }

  ngOnDestroy() {
    this.destroy$.next();
    this.destroy$.complete();
  }

  private _getFirstNonEmptyIdentifier(): string {
    const museum = String(this.museumNumberControl.value || '').trim();
    const pNum = String(this.pNumberControl.value || '').trim();
    const pub = String(this.publicationNumberControl.value || '').trim();
    return museum || pNum || pub;
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

  onAutocompleteClosed(): void {
    this.autocompleteOpen = false;
    this.autoClosedAt = Date.now();
  }

  onEnter(event: Event): void {
    // If the autocomplete dropdown is open or just closed (Enter selected an item), skip save
    if (this.autocompleteOpen || (Date.now() - this.autoClosedAt) < 200) {
      return;
    }
    this.onSave();
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

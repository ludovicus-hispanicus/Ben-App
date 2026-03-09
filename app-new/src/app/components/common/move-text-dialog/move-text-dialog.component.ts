import { Component, Inject } from '@angular/core';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';
import { ProjectPreview } from '../../../models/cured';

export interface MoveTextDialogData {
  projects: ProjectPreview[];
  currentProjectId: number | null;
  selectedCount: number;  // how many texts are currently selected
}

export interface MoveTextDialogResult {
  projectId: number | null;
  moveAll: boolean;  // true = move all selected, false = move only the clicked one
}

@Component({
  selector: 'app-move-text-dialog',
  templateUrl: './move-text-dialog.component.html',
  styleUrls: ['./move-text-dialog.component.scss']
})
export class MoveTextDialogComponent {
  selectedProjectId: number | null = null;
  moveAll = false;

  constructor(
    public dialogRef: MatDialogRef<MoveTextDialogComponent>,
    @Inject(MAT_DIALOG_DATA) public data: MoveTextDialogData
  ) {
    this.selectedProjectId = data.currentProjectId;
  }

  get availableProjects(): ProjectPreview[] {
    return this.data.projects.filter(p => p.project_id !== this.data.currentProjectId);
  }

  get hasMultipleSelected(): boolean {
    return this.data.selectedCount > 1;
  }

  onCancel(): void {
    this.dialogRef.close(undefined);
  }

  onMove(): void {
    this.dialogRef.close({ projectId: this.selectedProjectId, moveAll: this.moveAll } as MoveTextDialogResult);
  }
}

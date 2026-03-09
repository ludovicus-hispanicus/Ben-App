import { Component, OnInit, Inject } from '@angular/core';
import { MatDialogRef, MAT_DIALOG_DATA } from '@angular/material/dialog';
import { PagesService } from '../../../services/pages.service';
import { ProjectTreeNode } from '../../../models/pages';

export interface FolderPickerResult {
  project_id: string;
  project_name: string;
}

interface FlatFolder {
  project_id: string;
  name: string;
  image_count: number;
  total_image_count: number;
  depth: number;
  hasChildren: boolean;
  expanded: boolean;
  children: ProjectTreeNode[];
}

@Component({
  selector: 'app-folder-picker-dialog',
  templateUrl: './folder-picker-dialog.component.html',
  styleUrls: ['./folder-picker-dialog.component.scss']
})
export class FolderPickerDialogComponent implements OnInit {
  tree: ProjectTreeNode[] = [];
  flatFolders: FlatFolder[] = [];
  isLoading = false;
  selectedProjectId: string | null = null;
  newFolderName = '';
  isCreating = false;

  constructor(
    public dialogRef: MatDialogRef<FolderPickerDialogComponent>,
    private pagesService: PagesService,
    @Inject(MAT_DIALOG_DATA) public data: { title?: string }
  ) {}

  ngOnInit(): void {
    this.loadTree();
  }

  loadTree(): void {
    // Remember which nodes were expanded before reload
    const expandedIds = new Set<string>();
    this.collectExpanded(this.tree, expandedIds);

    this.isLoading = true;
    this.pagesService.getTree().subscribe({
      next: (tree) => {
        this.tree = tree;
        // Restore expanded state
        this.restoreExpanded(this.tree, expandedIds);
        this.rebuildFlat();
        this.isLoading = false;
      },
      error: () => {
        this.isLoading = false;
      }
    });
  }

  private collectExpanded(nodes: ProjectTreeNode[], ids: Set<string>): void {
    for (const node of nodes) {
      if (node.expanded) { ids.add(node.project_id); }
      if (node.children) { this.collectExpanded(node.children, ids); }
    }
  }

  private restoreExpanded(nodes: ProjectTreeNode[], ids: Set<string>): void {
    for (const node of nodes) {
      if (ids.has(node.project_id)) { node.expanded = true; }
      if (node.children) { this.restoreExpanded(node.children, ids); }
    }
  }

  private rebuildFlat(): void {
    this.flatFolders = [];
    this.flatten(this.tree, 0);
  }

  private flatten(nodes: ProjectTreeNode[], depth: number): void {
    for (const node of nodes) {
      const flat: FlatFolder = {
        project_id: node.project_id,
        name: node.name,
        image_count: node.image_count,
        total_image_count: node.total_image_count,
        depth,
        hasChildren: node.children && node.children.length > 0,
        expanded: node.expanded || false,
        children: node.children || []
      };
      this.flatFolders.push(flat);
      if (flat.expanded && flat.hasChildren) {
        this.flatten(node.children, depth + 1);
      }
    }
  }

  toggleExpand(folder: FlatFolder, event: Event): void {
    event.stopPropagation();
    folder.expanded = !folder.expanded;
    // Sync back to tree node
    const node = this.findNode(this.tree, folder.project_id);
    if (node) { node.expanded = folder.expanded; }
    this.rebuildFlat();
  }

  private findNode(nodes: ProjectTreeNode[], id: string): ProjectTreeNode | null {
    for (const node of nodes) {
      if (node.project_id === id) { return node; }
      if (node.children) {
        const found = this.findNode(node.children, id);
        if (found) { return found; }
      }
    }
    return null;
  }

  selectProject(folder: FlatFolder): void {
    this.selectedProjectId = folder.project_id;
  }

  isSelected(folder: FlatFolder): boolean {
    return this.selectedProjectId === folder.project_id;
  }

  createFolder(): void {
    const name = this.newFolderName.trim();
    if (!name) return;

    this.isCreating = true;
    // If a folder is selected, create inside it; otherwise create at root
    const parentId = this.selectedProjectId || undefined;
    this.pagesService.createProject(name, parentId).subscribe({
      next: (response) => {
        this.isCreating = false;
        this.newFolderName = '';
        // Mark parent as expanded so it stays open after reload
        if (parentId) {
          const parentNode = this.findNode(this.tree, parentId);
          if (parentNode) { parentNode.expanded = true; }
        }
        // Select the newly created folder and refresh tree
        this.selectedProjectId = response.project_id;
        this.loadTree();
      },
      error: () => {
        this.isCreating = false;
      }
    });
  }

  getSelectedFolderName(): string {
    const folder = this.flatFolders.find(f => f.project_id === this.selectedProjectId);
    return folder ? folder.name : '';
  }

  confirm(): void {
    if (!this.selectedProjectId) return;
    const folder = this.flatFolders.find(f => f.project_id === this.selectedProjectId);
    if (folder) {
      this.dialogRef.close({
        project_id: folder.project_id,
        project_name: folder.name
      } as FolderPickerResult);
    }
  }

  onCancel(): void {
    this.dialogRef.close(null);
  }
}

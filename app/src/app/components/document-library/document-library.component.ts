import { Component, OnInit, HostListener, ViewChildren, QueryList, ElementRef } from '@angular/core';
import { Router } from '@angular/router';
import { PagesService } from '../../services/pages.service';
import { ProjectInfo, ProjectDetail, PageInfo, UploadResponse, ProjectTreeNode } from '../../models/pages';
import { NotificationService } from '../../services/notification.service';
import { MatDialog } from '@angular/material/dialog';
import { ConfirmDialogComponent } from '../common/confirm-dialog/confirm-dialog.component';
import { PageRangeDialogComponent, PageRangeDialogResult } from '../common/page-range-dialog/page-range-dialog.component';
import { environment } from '../../../environments/environment';

@Component({
  selector: 'app-document-library',
  templateUrl: './document-library.component.html',
  styleUrls: ['./document-library.component.scss']
})
export class DocumentLibraryComponent implements OnInit {
  // Tree state
  projectTree: ProjectTreeNode[] = [];
  selectedFolder: ProjectTreeNode | null = null;
  breadcrumb: ProjectTreeNode[] = [];
  currentSubfolders: ProjectTreeNode[] = [];

  isLoading = false;
  isUploading = false;

  // Create folder
  newFolderName = '';

  // PDF upload (root)
  uploadProjectName = '';
  uploadResult: UploadResponse | null = null;

  // Project detail view (pages)
  openProject: ProjectDetail | null = null;

  // Page selection
  selectedPages: Set<number> = new Set();
  lastSelectedIndex: number = -1;

  // Folder selection
  selectedFolders: Set<string> = new Set();
  lastSelectedFolderIndex: number = -1;

  // Drag & drop (folders)
  draggedFolder: ProjectTreeNode | null = null;
  dragOverFolderId: string | null = null;
  dragOverRoot = false;

  // Drag & drop (file upload)
  fileDragOver = false;
  private fileDragCounter = 0;

  // View mode
  viewMode: 'grid' | 'list' = 'grid';

  // Sorting
  sortColumn: 'name' | 'type' | 'size' | 'date' | 'page' = 'page';
  sortDirection: 'asc' | 'desc' = 'asc';

  // Page search/jump
  pageSearchQuery = '';

  // Viewer
  viewerPage: PageInfo | null = null;
  viewerIndex = -1;

  // Inline rename
  editingNode: ProjectTreeNode | null = null;
  editingName = '';
  private renameClickTimer: any = null;
  private renameCancelled = false;

  // Context menu
  contextMenuVisible = false;
  contextMenuX = 0;
  contextMenuY = 0;
  contextMenuNode: ProjectTreeNode | null = null;

  @ViewChildren('renameInput') renameInputs!: QueryList<ElementRef>;

  constructor(
    private pagesService: PagesService,
    private notificationService: NotificationService,
    private dialog: MatDialog,
    private router: Router
  ) {}

  ngOnInit(): void {
    this.loadTree();
  }

  // ============== Tree ==============

  loadTree(): void {
    this.isLoading = true;
    this.pagesService.getTree().subscribe({
      next: (tree) => {
        // Preserve expanded state from previous tree
        const expandedIds = new Set<string>();
        this.collectExpandedIds(this.projectTree, expandedIds);
        this.projectTree = tree;
        this.restoreExpandedState(this.projectTree, expandedIds);

        // Update current view if a folder is selected
        if (this.selectedFolder) {
          const found = this.findNodeInTree(this.projectTree, this.selectedFolder.project_id);
          if (found) {
            this.selectedFolder = found;
            this.currentSubfolders = found.children || [];
            this.breadcrumb = this.computeBreadcrumb(this.projectTree, found.project_id);
          }
        } else {
          this.currentSubfolders = this.projectTree;
        }

        this.isLoading = false;
      },
      error: () => {
        this.notificationService.showError('Failed to load library');
        this.isLoading = false;
      }
    });
  }

  private collectExpandedIds(nodes: ProjectTreeNode[], ids: Set<string>): void {
    for (const node of nodes) {
      if (node.expanded) { ids.add(node.project_id); }
      if (node.children) { this.collectExpandedIds(node.children, ids); }
    }
  }

  private restoreExpandedState(nodes: ProjectTreeNode[], ids: Set<string>): void {
    for (const node of nodes) {
      node.expanded = ids.has(node.project_id);
      if (node.children) { this.restoreExpandedState(node.children, ids); }
    }
  }

  private findNodeInTree(nodes: ProjectTreeNode[], id: string): ProjectTreeNode | null {
    for (const node of nodes) {
      if (node.project_id === id) { return node; }
      if (node.children) {
        const found = this.findNodeInTree(node.children, id);
        if (found) { return found; }
      }
    }
    return null;
  }

  private computeBreadcrumb(tree: ProjectTreeNode[], targetId: string): ProjectTreeNode[] {
    const path: ProjectTreeNode[] = [];
    const find = (nodes: ProjectTreeNode[]): boolean => {
      for (const node of nodes) {
        path.push(node);
        if (node.project_id === targetId) { return true; }
        if (node.children && find(node.children)) { return true; }
        path.pop();
      }
      return false;
    };
    find(tree);
    return path;
  }

  private expandPathTo(targetId: string): void {
    const path = this.computeBreadcrumb(this.projectTree, targetId);
    for (const node of path) {
      node.expanded = true;
    }
  }

  // ============== Navigation ==============

  toggleExpand(node: ProjectTreeNode, event: Event): void {
    event.stopPropagation();
    node.expanded = !node.expanded;
  }

  selectFolder(node: ProjectTreeNode): void {
    this.openProject = null;
    this.clearSelection();
    this.clearFolderSelection();
    this.selectedFolder = node;
    this.currentSubfolders = node.children || [];
    this.breadcrumb = this.computeBreadcrumb(this.projectTree, node.project_id);
    this.expandPathTo(node.project_id);

    // Auto-load pages if this folder has images
    if (node.image_count > 0) {
      this.loadFolderPages(node);
    } else {
      this.openProject = null;
    }
  }

  private loadFolderPages(node: ProjectTreeNode): void {
    this.pagesService.getProject(node.project_id).subscribe({
      next: (detail) => {
        this.openProject = detail;
      },
      error: () => {
        // Silently fail — pages just won't show
      }
    });
  }

  // Single-click on content card: select (not navigate)
  selectFolderFromContent(node: ProjectTreeNode, event: MouseEvent): void {
    this.toggleFolderSelection(node, event);
  }

  // Double-click on content card: navigate into folder
  openFolderFromContent(node: ProjectTreeNode): void {
    clearTimeout(this.renameClickTimer);
    this.clearFolderSelection();
    this.selectFolder(node);
  }

  // ============== Folder Selection ==============

  toggleFolderSelection(folder: ProjectTreeNode, event: MouseEvent): void {
    const index = this.currentSubfolders.indexOf(folder);
    const id = folder.project_id;

    if (event.shiftKey && this.lastSelectedFolderIndex >= 0) {
      const start = Math.min(this.lastSelectedFolderIndex, index);
      const end = Math.max(this.lastSelectedFolderIndex, index);
      for (let i = start; i <= end; i++) {
        this.selectedFolders.add(this.currentSubfolders[i].project_id);
      }
    } else if (event.ctrlKey || event.metaKey) {
      if (this.selectedFolders.has(id)) {
        this.selectedFolders.delete(id);
      } else {
        this.selectedFolders.add(id);
      }
    } else {
      this.selectedFolders.clear();
      this.selectedFolders.add(id);
    }
    this.lastSelectedFolderIndex = index;
  }

  isFolderSelected(folder: ProjectTreeNode): boolean {
    return this.selectedFolders.has(folder.project_id);
  }

  selectAllFolders(): void {
    if (this.selectedFolders.size === this.currentSubfolders.length) {
      this.selectedFolders.clear();
    } else {
      this.currentSubfolders.forEach(f => this.selectedFolders.add(f.project_id));
    }
  }

  clearFolderSelection(): void {
    this.selectedFolders.clear();
    this.lastSelectedFolderIndex = -1;
  }

  deleteSelectedFolders(): void {
    if (this.selectedFolders.size === 0) { return; }
    const count = this.selectedFolders.size;

    const dialogRef = this.dialog.open(ConfirmDialogComponent, {
      data: {
        title: 'Delete Folders',
        message: `Delete ${count} selected folder(s) and all their pages?`,
        confirmText: 'Delete',
        warn: true
      }
    });

    dialogRef.afterClosed().subscribe(confirmed => {
      if (!confirmed) { return; }
      const ids = Array.from(this.selectedFolders);
      let completed = 0;
      let errors = 0;
      ids.forEach(id => {
        this.pagesService.deleteProject(id).subscribe({
          next: () => {
            completed++;
            if (completed + errors === ids.length) {
              this.notificationService.showSuccess(`Deleted ${completed} folder(s)`);
              this.clearFolderSelection();
              this.loadTree();
            }
          },
          error: () => {
            errors++;
            if (completed + errors === ids.length) {
              this.notificationService.showError(`Deleted ${completed}, failed ${errors}`);
              this.clearFolderSelection();
              this.loadTree();
            }
          }
        });
      });
    });
  }

  navigateBreadcrumb(node: ProjectTreeNode | null): void {
    if (!node) {
      // Go to root
      this.selectedFolder = null;
      this.openProject = null;
      this.breadcrumb = [];
      this.currentSubfolders = this.projectTree;
      this.clearSelection();
      this.clearFolderSelection();
    } else {
      this.selectFolder(node);
    }
  }

  openFolderPages(folder: ProjectTreeNode): void {
    this.isLoading = true;
    this.pagesService.getProject(folder.project_id).subscribe({
      next: (detail) => {
        this.openProject = detail;
        this.isLoading = false;
      },
      error: () => {
        this.notificationService.showError('Failed to load pages');
        this.isLoading = false;
      }
    });
  }

  closeFolderPages(): void {
    this.openProject = null;
    this.clearSelection();
  }

  // ============== Create / Delete / Rename ==============

  createFolder(): void {
    const name = this.newFolderName.trim();
    if (!name) { return; }
    const parentId = this.selectedFolder?.project_id;
    this.pagesService.createProject(name, parentId).subscribe({
      next: () => {
        this.newFolderName = '';
        this.loadTree();
      },
      error: (err) => {
        this.notificationService.showError('Failed to create folder: ' + (err.error?.detail || err.message));
      }
    });
  }

  deleteFolder(): void {
    if (!this.selectedFolder) { return; }
    this.deleteFolderCard(this.selectedFolder);
  }

  deleteFolderCard(folder: ProjectTreeNode, event?: Event): void {
    if (event) {
      event.stopPropagation();
    }

    const dialogRef = this.dialog.open(ConfirmDialogComponent, {
      data: {
        title: 'Delete Folder',
        message: `Delete "${folder.name}" and all its pages?`,
        confirmText: 'Delete',
        warn: true
      }
    });

    dialogRef.afterClosed().subscribe(confirmed => {
      if (!confirmed) { return; }
      this.pagesService.deleteProject(folder.project_id).subscribe({
        next: () => {
          this.notificationService.showSuccess(`Deleted "${folder.name}"`);
          if (this.selectedFolder?.project_id === folder.project_id) {
            this.selectedFolder = null;
            this.breadcrumb = [];
            this.currentSubfolders = [];
          }
          this.loadTree();
        },
        error: (err) => {
          this.notificationService.showError(err.error?.detail || 'Failed to delete folder');
        }
      });
    });
  }

  // ============== Inline Rename ==============

  onNameClick(node: ProjectTreeNode, event: MouseEvent): void {
    event.stopPropagation();
    // Only start rename if this node is already selected (slow double-click)
    if (this.selectedFolder?.project_id === node.project_id) {
      clearTimeout(this.renameClickTimer);
      this.renameClickTimer = setTimeout(() => {
        this.startRename(node);
      }, 400);
    }
  }

  onSubfolderNameClick(folder: ProjectTreeNode, event: MouseEvent): void {
    event.stopPropagation();
    // Only start rename if this folder is already selected
    if (this.selectedFolders.has(folder.project_id)) {
      clearTimeout(this.renameClickTimer);
      this.renameClickTimer = setTimeout(() => {
        this.startRename(folder);
      }, 400);
    }
  }

  startRename(node: ProjectTreeNode): void {
    this.editingNode = node;
    this.editingName = node.name;
    this.renameCancelled = false;
    setTimeout(() => {
      const inputs = this.renameInputs.toArray();
      if (inputs.length > 0) {
        const input = inputs[0].nativeElement as HTMLInputElement;
        input.focus();
        input.select();
      }
    });
  }

  confirmRename(): void {
    if (!this.editingNode || this.renameCancelled) { return; }
    const node = this.editingNode;
    const newName = this.editingName.trim();
    this.editingNode = null;

    if (!newName || newName === node.name) { return; }

    this.pagesService.renameProject(node.project_id, newName).subscribe({
      next: () => {
        node.name = newName;
        this.notificationService.showSuccess(`Renamed to "${newName}"`);
      },
      error: () => {
        this.notificationService.showError('Failed to rename folder');
      }
    });
  }

  cancelRename(): void {
    this.renameCancelled = true;
    this.editingNode = null;
    this.editingName = '';
  }

  onRenameBlur(): void {
    // Small delay to allow cancelRename (Escape) to fire first
    setTimeout(() => {
      if (this.editingNode && !this.renameCancelled) {
        this.confirmRename();
      }
    }, 100);
  }

  // ============== Context Menu ==============

  onFolderContextMenu(node: ProjectTreeNode, event: MouseEvent): void {
    event.preventDefault();
    event.stopPropagation();
    this.contextMenuNode = node;
    this.contextMenuX = event.clientX;
    this.contextMenuY = event.clientY;
    this.contextMenuVisible = true;
  }

  startRenameFromMenu(): void {
    if (!this.contextMenuNode) { return; }
    const node = this.contextMenuNode;
    this.contextMenuVisible = false;
    this.startRename(node);
  }

  deleteFolderFromMenu(): void {
    if (!this.contextMenuNode) { return; }
    const node = this.contextMenuNode;
    this.contextMenuVisible = false;
    this.deleteFolderCard(node);
  }

  @HostListener('document:click')
  onDocumentClick(): void {
    this.contextMenuVisible = false;
  }

  // ============== Drag & Drop ==============

  onFolderDragStart(node: ProjectTreeNode, event: DragEvent): void {
    // If dragging a selected folder, all selected will move; otherwise just this one
    if (!this.selectedFolders.has(node.project_id)) {
      this.clearFolderSelection();
      this.selectedFolders.add(node.project_id);
    }
    this.draggedFolder = node;
    if (event.dataTransfer) {
      event.dataTransfer.effectAllowed = 'move';
      event.dataTransfer.setData('text/plain', node.project_id);
    }
  }

  onFolderDragOver(targetNode: ProjectTreeNode, event: DragEvent): void {
    if (!this.draggedFolder || this.draggedFolder.project_id === targetNode.project_id) { return; }
    event.preventDefault();
    if (event.dataTransfer) { event.dataTransfer.dropEffect = 'move'; }
    this.dragOverFolderId = targetNode.project_id;
    this.dragOverRoot = false;
  }

  onFolderDragLeave(event: DragEvent): void {
    this.dragOverFolderId = null;
    this.dragOverRoot = false;
  }

  onFolderDrop(targetNode: ProjectTreeNode, event: DragEvent): void {
    event.preventDefault();
    event.stopPropagation();
    this.dragOverFolderId = null;

    if (!this.draggedFolder) {
      return;
    }

    // Collect IDs to move (selected folders, excluding the drop target)
    const idsToMove = this.selectedFolders.size > 0
      ? Array.from(this.selectedFolders).filter(id => id !== targetNode.project_id)
      : [this.draggedFolder.project_id].filter(id => id !== targetNode.project_id);

    this.draggedFolder = null;
    if (idsToMove.length === 0) { return; }

    this.batchMove(idsToMove, targetNode.project_id, targetNode.name);
  }

  onFolderDragEnd(event: DragEvent): void {
    this.draggedFolder = null;
    this.dragOverFolderId = null;
    this.dragOverRoot = false;
  }

  onRootDragOver(event: DragEvent): void {
    if (!this.draggedFolder) { return; }
    event.preventDefault();
    if (event.dataTransfer) { event.dataTransfer.dropEffect = 'move'; }
    this.dragOverRoot = true;
    this.dragOverFolderId = null;
  }

  onRootDrop(event: DragEvent): void {
    event.preventDefault();
    event.stopPropagation();
    this.dragOverRoot = false;

    if (!this.draggedFolder) { return; }

    const idsToMove = this.selectedFolders.size > 0
      ? Array.from(this.selectedFolders)
      : [this.draggedFolder.project_id];

    this.draggedFolder = null;
    if (idsToMove.length === 0) { return; }

    this.batchMove(idsToMove, null, 'root');
  }

  private batchMove(ids: string[], targetParentId: string | null, targetName: string): void {
    let completed = 0;
    let errors = 0;
    ids.forEach(id => {
      this.pagesService.moveProject(id, targetParentId).subscribe({
        next: () => {
          completed++;
          if (completed + errors === ids.length) {
            const msg = ids.length === 1
              ? `Moved folder into "${targetName}"`
              : `Moved ${completed} folder(s) into "${targetName}"`;
            this.notificationService.showSuccess(msg);
            this.clearFolderSelection();
            this.loadTree();
          }
        },
        error: () => {
          errors++;
          if (completed + errors === ids.length) {
            this.notificationService.showError(`Moved ${completed}, failed ${errors}`);
            this.clearFolderSelection();
            this.loadTree();
          }
        }
      });
    });
  }

  // ============== Upload ==============

  onPdfSelected(event: Event): void {
    const input = event.target as HTMLInputElement;
    if (!input.files || input.files.length === 0) { return; }

    if (!this.uploadProjectName.trim()) {
      this.notificationService.showError('Please enter a project name');
      input.value = '';
      return;
    }

    const file = input.files[0];
    const projectName = this.uploadProjectName.trim();
    input.value = '';

    // Get page count and show range dialog
    this.isUploading = true;
    this.uploadResult = null;

    this.pagesService.getPdfPageCount(file).subscribe({
      next: (info) => {
        this.isUploading = false;
        const dialogRef = this.dialog.open(PageRangeDialogComponent, {
          width: '400px',
          data: { filename: file.name, pageCount: info.page_count }
        });
        dialogRef.afterClosed().subscribe((result: PageRangeDialogResult | null) => {
          if (!result) { return; }
          this.isUploading = true;
          this.pagesService.uploadPdf(file, projectName, result.pageFrom, result.pageTo, result.dpi).subscribe({
            next: (response) => {
              this.uploadResult = response;
              this.isUploading = false;
              this.notificationService.showSuccess(response.message);
              this.uploadProjectName = '';
              this.loadTree();
            },
            error: (err) => {
              this.isUploading = false;
              this.notificationService.showError('Upload failed: ' + (err.error?.detail || err.message));
            }
          });
        });
      },
      error: () => {
        // Fallback: upload all pages
        this.pagesService.uploadPdf(file, projectName).subscribe({
          next: (response) => {
            this.uploadResult = response;
            this.isUploading = false;
            this.notificationService.showSuccess(response.message);
            this.uploadProjectName = '';
            this.loadTree();
          },
          error: (err) => {
            this.isUploading = false;
            this.notificationService.showError('Upload failed: ' + (err.error?.detail || err.message));
          }
        });
      }
    });
  }

  onTreeFileSelected(event: Event): void {
    const input = event.target as HTMLInputElement;
    if (!input.files) { return; }
    const projectId = this.selectedFolder?.project_id;
    for (let i = 0; i < input.files.length; i++) {
      this.uploadFile(input.files[i], projectId);
    }
    input.value = '';
  }

  onFolderFileSelected(event: Event): void {
    if (!this.selectedFolder) { return; }
    const input = event.target as HTMLInputElement;
    if (!input.files) { return; }
    for (let i = 0; i < input.files.length; i++) {
      this.uploadFile(input.files[i], this.selectedFolder.project_id);
    }
    input.value = '';
  }

  onProjectFileSelected(event: Event): void {
    if (!this.openProject) { return; }
    const input = event.target as HTMLInputElement;
    if (input.files) {
      for (let i = 0; i < input.files.length; i++) {
        this.uploadFile(input.files[i], this.openProject.project_id);
      }
    }
    input.value = '';
  }

  uploadFile(file: File, projectId?: string): void {
    const validTypes = ['application/pdf', 'image/png', 'image/jpeg'];
    if (!validTypes.includes(file.type) && !file.name.toLowerCase().endsWith('.pdf')) {
      this.notificationService.showError('Please upload PDF, PNG, or JPEG files.');
      return;
    }

    const isPdf = file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf');
    if (isPdf) {
      this.uploadPdfWithRangeDialog(file, projectId);
    } else {
      this.doUploadFile(file, projectId);
    }
  }

  private uploadPdfWithRangeDialog(file: File, projectId?: string): void {
    this.isUploading = true;
    this.pagesService.getPdfPageCount(file).subscribe({
      next: (info) => {
        this.isUploading = false;
        const dialogRef = this.dialog.open(PageRangeDialogComponent, {
          width: '400px',
          data: { filename: file.name, pageCount: info.page_count }
        });
        dialogRef.afterClosed().subscribe((result: PageRangeDialogResult | null) => {
          if (!result) { return; } // cancelled
          this.doUploadFile(file, projectId, result.pageFrom, result.pageTo, result.dpi);
        });
      },
      error: () => {
        this.isUploading = false;
        // Fallback: upload without range if page count fails
        this.doUploadFile(file, projectId);
      }
    });
  }

  private doUploadFile(file: File, projectId?: string, pageFrom?: number, pageTo?: number, dpi?: number): void {
    this.isUploading = true;
    this.pagesService.uploadFile(file, projectId, pageFrom, pageTo, dpi).subscribe({
      next: (response) => {
        this.notificationService.showSuccess(response.message);
        this.isUploading = false;
        if (this.openProject && projectId) {
          this.pagesService.getProject(projectId).subscribe(detail => {
            this.openProject = detail;
          });
        }
        this.loadTree();
      },
      error: (err) => {
        this.notificationService.showError('Upload failed: ' + (err.error?.detail || err.message));
        this.isUploading = false;
      }
    });
  }

  // ============== Drag & Drop File Upload ==============

  onFileDragOver(event: DragEvent): void {
    // Only handle file drags, not folder-move drags
    if (this.draggedFolder) { return; }
    if (!event.dataTransfer?.types.includes('Files')) { return; }
    event.preventDefault();
    event.stopPropagation();
    if (event.dataTransfer) { event.dataTransfer.dropEffect = 'copy'; }
    this.fileDragCounter++;
    this.fileDragOver = true;
  }

  onFileDragLeave(event: DragEvent): void {
    if (this.draggedFolder) { return; }
    event.preventDefault();
    this.fileDragCounter--;
    if (this.fileDragCounter <= 0) {
      this.fileDragOver = false;
      this.fileDragCounter = 0;
    }
  }

  onFileDrop(event: DragEvent): void {
    if (this.draggedFolder) { return; }
    event.preventDefault();
    event.stopPropagation();
    this.fileDragOver = false;
    this.fileDragCounter = 0;

    const files = event.dataTransfer?.files;
    if (!files || files.length === 0) { return; }

    const projectId = this.selectedFolder?.project_id || this.openProject?.project_id;
    for (let i = 0; i < files.length; i++) {
      this.uploadFile(files[i], projectId);
    }
  }

  // ============== Image helpers ==============

  getThumbnailUrl(page: PageInfo): string {
    return `${environment.apiUrl}${page.thumbnail_url}`;
  }

  getFullImageUrl(page: PageInfo): string {
    return `${environment.apiUrl}${page.full_url}`;
  }

  // ============== Page Selection ==============

  togglePageSelection(page: PageInfo, event: MouseEvent): void {
    if (!this.openProject) { return; }
    const index = this.openProject.pages.indexOf(page);
    const pageNum = page.page_number;

    if (event.shiftKey && this.lastSelectedIndex >= 0) {
      const start = Math.min(this.lastSelectedIndex, index);
      const end = Math.max(this.lastSelectedIndex, index);
      for (let i = start; i <= end; i++) {
        this.selectedPages.add(this.openProject.pages[i].page_number);
      }
    } else if (event.ctrlKey || event.metaKey) {
      if (this.selectedPages.has(pageNum)) {
        this.selectedPages.delete(pageNum);
      } else {
        this.selectedPages.add(pageNum);
      }
    } else {
      this.selectedPages.clear();
      this.selectedPages.add(pageNum);
    }
    this.lastSelectedIndex = index;
  }

  isPageSelected(page: PageInfo): boolean {
    return this.selectedPages.has(page.page_number);
  }

  selectAllPages(): void {
    if (!this.openProject) { return; }
    if (this.selectedPages.size === this.openProject.pages.length) {
      this.selectedPages.clear();
    } else {
      this.openProject.pages.forEach(p => this.selectedPages.add(p.page_number));
    }
  }

  clearSelection(): void {
    this.selectedPages.clear();
    this.lastSelectedIndex = -1;
  }

  onContentBackgroundClick(event: MouseEvent): void {
    const target = event.target as HTMLElement;
    if (target.closest('.thumbnail-card') || target.closest('.details-row') || target.closest('.subfolder-card')) {
      return;
    }
    this.clearSelection();
    this.clearFolderSelection();
  }

  onTreeBackgroundClick(event: MouseEvent): void {
    const target = event.target as HTMLElement;
    if (target.closest('.tree-node')) { return; }
    this.navigateBreadcrumb(null);
  }

  // ============== Page Search / Jump ==============

  get filteredPages(): PageInfo[] {
    if (!this.openProject) { return []; }
    let pages = this.openProject.pages;

    const q = this.pageSearchQuery.trim();
    if (q) {
      const lower = q.toLowerCase();
      pages = pages.filter(p => p.filename.toLowerCase().includes(lower));
    }

    return [...pages].sort((a, b) => {
      let cmp = 0;
      switch (this.sortColumn) {
        case 'name':
          cmp = a.filename.localeCompare(b.filename);
          break;
        case 'type':
          cmp = (a.file_type || '').localeCompare(b.file_type || '');
          break;
        case 'size':
          cmp = (a.file_size || 0) - (b.file_size || 0);
          break;
        case 'date':
          cmp = (a.modified_at || '').localeCompare(b.modified_at || '');
          break;
        case 'page':
          cmp = a.page_number - b.page_number;
          break;
      }
      return this.sortDirection === 'asc' ? cmp : -cmp;
    });
  }

  toggleSort(column: 'name' | 'type' | 'size' | 'date' | 'page'): void {
    if (this.sortColumn === column) {
      this.sortDirection = this.sortDirection === 'asc' ? 'desc' : 'asc';
    } else {
      this.sortColumn = column;
      this.sortDirection = 'asc';
    }
  }

  onPageSearchEnter(): void {
    if (!this.openProject) { return; }
    const q = this.pageSearchQuery.trim();
    const num = parseInt(q, 10);
    if (!isNaN(num) && num >= 1 && num <= this.openProject.pages.length) {
      // Jump to that page number — scroll the thumbnail into view
      const el = document.getElementById('page-thumb-' + num);
      if (el) {
        el.scrollIntoView({ behavior: 'smooth', block: 'center' });
      }
    }
  }

  clearPageSearch(): void {
    this.pageSearchQuery = '';
  }

  formatFileSize(bytes: number): string {
    if (!bytes) { return '—'; }
    if (bytes < 1024) { return bytes + ' B'; }
    if (bytes < 1048576) { return (bytes / 1024).toFixed(1) + ' KB'; }
    return (bytes / 1048576).toFixed(1) + ' MB';
  }

  formatDate(iso: string): string {
    if (!iso) { return '—'; }
    const d = new Date(iso);
    return d.toLocaleDateString() + ' ' + d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }

  // ============== Viewer ==============

  openViewer(page: PageInfo): void {
    if (!this.openProject) { return; }
    this.viewerPage = page;
    this.viewerIndex = this.openProject.pages.indexOf(page);
  }

  closeViewer(): void {
    this.viewerPage = null;
    this.viewerIndex = -1;
  }

  viewerPrev(): void {
    if (!this.openProject || this.viewerIndex <= 0) { return; }
    this.viewerIndex--;
    this.viewerPage = this.openProject.pages[this.viewerIndex];
  }

  viewerNext(): void {
    if (!this.openProject || this.viewerIndex >= this.openProject.pages.length - 1) { return; }
    this.viewerIndex++;
    this.viewerPage = this.openProject.pages[this.viewerIndex];
  }

  @HostListener('document:keydown', ['$event'])
  onKeydown(event: KeyboardEvent): void {
    if (this.viewerPage) {
      if (event.key === 'Escape') { this.closeViewer(); }
      else if (event.key === 'ArrowLeft') { this.viewerPrev(); }
      else if (event.key === 'ArrowRight') { this.viewerNext(); }
      return;
    }
    if (event.key === 'Delete') {
      if (this.selectedPages.size > 0) {
        this.deleteSelectedPages();
      } else if (this.selectedFolders.size > 0) {
        this.deleteSelectedFolders();
      }
    }
    if (event.ctrlKey && event.key === 'a') {
      event.preventDefault();
      if (this.openProject) {
        this.selectAllPages();
      } else {
        this.selectAllFolders();
      }
    }
  }

  // ============== Open in Tool ==============

  openInTool(route: string): void {
    if (!this.viewerPage || !this.openProject) { return; }
    this.router.navigate(['/' + route], {
      queryParams: {
        library_project: this.openProject.project_id,
        library_page: this.viewerPage.page_number
      }
    });
  }

  // ============== Download ==============

  downloadFolder(): void {
    if (!this.selectedFolder) { return; }
    const url = this.pagesService.downloadProjectUrl(this.selectedFolder.project_id);
    window.open(url, '_blank');
  }

  downloadOpenProject(): void {
    if (!this.openProject) { return; }
    const url = this.pagesService.downloadProjectUrl(this.openProject.project_id);
    window.open(url, '_blank');
  }

  // ============== Delete Pages ==============

  deletePage(page: PageInfo, event: Event): void {
    event.stopPropagation();
    if (!this.openProject) { return; }

    const dialogRef = this.dialog.open(ConfirmDialogComponent, {
      data: {
        title: 'Delete Page',
        message: `Delete "${page.filename}"?`,
        confirmText: 'Delete',
        warn: true
      }
    });

    dialogRef.afterClosed().subscribe(confirmed => {
      if (!confirmed || !this.openProject) { return; }
      this.pagesService.deletePages(this.openProject.project_id, [page.filename]).subscribe({
        next: () => {
          this.selectedPages.delete(page.page_number);
          this.notificationService.showSuccess(`Deleted ${page.filename}`);
          this.refreshOpenProject();
          this.loadTree();
        },
        error: () => this.notificationService.showError('Failed to delete page')
      });
    });
  }

  deleteSelectedPages(): void {
    if (!this.openProject || this.selectedPages.size === 0) { return; }
    const count = this.selectedPages.size;

    const dialogRef = this.dialog.open(ConfirmDialogComponent, {
      data: {
        title: 'Delete Pages',
        message: `Delete ${count} selected page(s)?`,
        confirmText: 'Delete',
        warn: true
      }
    });

    dialogRef.afterClosed().subscribe(confirmed => {
      if (!confirmed || !this.openProject) { return; }
      // Resolve selected page numbers to filenames
      const filenames = this.openProject.pages
        .filter(p => this.selectedPages.has(p.page_number))
        .map(p => p.filename);
      this.pagesService.deletePages(this.openProject.project_id, filenames).subscribe({
        next: () => {
          this.notificationService.showSuccess(`Deleted ${count} page(s)`);
          this.selectedPages.clear();
          this.lastSelectedIndex = -1;
          this.refreshOpenProject();
          this.loadTree();
        },
        error: () => this.notificationService.showError('Failed to delete pages')
      });
    });
  }

  private refreshOpenProject(): void {
    if (!this.openProject) { return; }
    this.pagesService.getProject(this.openProject.project_id).subscribe(detail => {
      this.openProject = detail;
    });
  }
}

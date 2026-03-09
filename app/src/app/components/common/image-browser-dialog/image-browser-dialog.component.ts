import { Component, OnInit } from '@angular/core';
import { MatDialogRef } from '@angular/material/dialog';
import { PagesService } from '../../../services/pages.service';
import { ProjectTreeNode, ProjectDetail, PageInfo, SelectedPage } from '../../../models/pages';
import { environment } from '../../../../environments/environment';

@Component({
  selector: 'app-image-browser-dialog',
  templateUrl: './image-browser-dialog.component.html',
  styleUrls: ['./image-browser-dialog.component.scss']
})
export class ImageBrowserDialogComponent implements OnInit {
  tree: ProjectTreeNode[] = [];
  selectedProject: ProjectDetail | null = null;
  currentNode: ProjectTreeNode | null = null;
  breadcrumb: ProjectTreeNode[] = [];
  isLoading = false;
  isUploading = false;
  viewMode: 'grid' | 'list' = 'grid';

  // Search
  pageSearchQuery = '';

  // Multi-select
  selectedPages: Set<number> = new Set();
  private lastSelectedIndex: number = -1;

  constructor(
    public dialogRef: MatDialogRef<ImageBrowserDialogComponent>,
    private pagesService: PagesService
  ) {}

  ngOnInit(): void {
    this.loadTree();
  }

  loadTree(): void {
    this.isLoading = true;
    console.log('[ImageBrowser] loadTree() called, fetching tree...');
    this.pagesService.getTree().subscribe({
      next: (tree) => {
        console.log('[ImageBrowser] tree loaded:', tree?.length, 'root items', tree);
        this.tree = tree;
        this.isLoading = false;
      },
      error: (err) => {
        console.error('[ImageBrowser] tree load FAILED:', err);
        this.isLoading = false;
      }
    });
  }

  toggleExpand(node: ProjectTreeNode, event: Event): void {
    event.stopPropagation();
    node.expanded = !node.expanded;
  }

  openProject(node: ProjectTreeNode): void {
    this.isLoading = true;
    this.currentNode = node;
    this.breadcrumb = this.buildBreadcrumb(node, this.tree);
    this.pagesService.getProject(node.project_id).subscribe({
      next: (detail) => {
        this.selectedProject = detail;
        this.selectedPages.clear();
        this.lastSelectedIndex = -1;
        this.isLoading = false;
      },
      error: () => {
        this.isLoading = false;
      }
    });
  }

  private buildBreadcrumb(target: ProjectTreeNode, nodes: ProjectTreeNode[], path: ProjectTreeNode[] = []): ProjectTreeNode[] {
    for (const node of nodes) {
      if (node.project_id === target.project_id) {
        return [...path, node];
      }
      if (node.children?.length) {
        const result = this.buildBreadcrumb(target, node.children, [...path, node]);
        if (result.length) return result;
      }
    }
    return [];
  }

  get filteredPages(): PageInfo[] {
    if (!this.selectedProject) return [];
    const q = this.pageSearchQuery.trim();
    if (!q) return this.selectedProject.pages;
    const lower = q.toLowerCase();
    return this.selectedProject.pages.filter(p =>
      p.filename.toLowerCase().includes(lower)
    );
  }

  onPageSearchEnter(): void {
    if (!this.selectedProject) return;
    const q = this.pageSearchQuery.trim();
    const num = parseInt(q, 10);
    if (!isNaN(num) && num >= 1 && num <= this.selectedProject.pages.length) {
      const el = document.getElementById('browser-page-' + num);
      if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
  }

  clearPageSearch(): void {
    this.pageSearchQuery = '';
  }

  goBack(): void {
    this.selectedProject = null;
    this.currentNode = null;
    this.breadcrumb = [];
    this.selectedPages.clear();
    this.lastSelectedIndex = -1;
    this.pageSearchQuery = '';
  }

  togglePageSelection(page: PageInfo, event: MouseEvent): void {
    if (!this.selectedProject) return;

    const pages = this.selectedProject.pages;
    const index = pages.indexOf(page);
    const pageNum = page.page_number;

    if (event.shiftKey && this.lastSelectedIndex >= 0) {
      // Shift+click: select range
      const start = Math.min(this.lastSelectedIndex, index);
      const end = Math.max(this.lastSelectedIndex, index);
      for (let i = start; i <= end; i++) {
        this.selectedPages.add(pages[i].page_number);
      }
    } else if (event.ctrlKey || event.metaKey) {
      // Ctrl+click: toggle individual
      if (this.selectedPages.has(pageNum)) {
        this.selectedPages.delete(pageNum);
      } else {
        this.selectedPages.add(pageNum);
      }
    } else {
      // Plain click: clear and select only this
      this.selectedPages.clear();
      this.selectedPages.add(pageNum);
    }

    this.lastSelectedIndex = index;
  }

  isPageSelected(page: PageInfo): boolean {
    return this.selectedPages.has(page.page_number);
  }

  selectAll(): void {
    if (!this.selectedProject) return;
    if (this.selectedPages.size === this.selectedProject.pages.length) {
      this.selectedPages.clear();
    } else {
      for (const page of this.selectedProject.pages) {
        this.selectedPages.add(page.page_number);
      }
    }
  }

  loadPage(page: PageInfo): void {
    if (!this.selectedProject) return;
    const result: SelectedPage[] = [{
      project_id: this.selectedProject.project_id,
      project_name: this.selectedProject.name,
      page_number: page.page_number,
      filename: page.filename,
      image_url: `${environment.apiUrl}${page.full_url}`
    }];
    this.dialogRef.close(result);
  }

  loadSelected(): void {
    if (!this.selectedProject || this.selectedPages.size === 0) return;

    const results: SelectedPage[] = this.selectedProject.pages
      .filter(p => this.selectedPages.has(p.page_number))
      .map(p => ({
        project_id: this.selectedProject!.project_id,
        project_name: this.selectedProject!.name,
        page_number: p.page_number,
        filename: p.filename,
        image_url: `${environment.apiUrl}${p.full_url}`
      }));

    this.dialogRef.close(results);
  }

  formatFileSize(bytes: number): string {
    if (!bytes) return '—';
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
  }

  onUploadFile(event: Event): void {
    const input = event.target as HTMLInputElement;
    if (!input.files || input.files.length === 0) return;

    this.isUploading = true;
    const file = input.files[0];
    const projectId = this.selectedProject?.project_id;
    this.pagesService.uploadFile(file, projectId).subscribe({
      next: () => {
        this.isUploading = false;
        if (projectId) {
          this.openProject(this.currentNode!);
        } else {
          this.loadTree();
        }
      },
      error: () => {
        this.isUploading = false;
      }
    });
    input.value = '';
  }

  onUploadFolder(event: Event): void {
    const input = event.target as HTMLInputElement;
    if (!input.files || input.files.length === 0) return;

    const supportedExts = ['.png', '.jpg', '.jpeg', '.pdf'];
    const files: File[] = [];
    for (let i = 0; i < input.files.length; i++) {
      const name = input.files[i].name.toLowerCase();
      if (supportedExts.some(ext => name.endsWith(ext))) {
        files.push(input.files[i]);
      }
    }

    if (files.length === 0) {
      input.value = '';
      return;
    }

    this.isUploading = true;
    const projectId = this.selectedProject?.project_id;
    let completed = 0;

    for (const file of files) {
      this.pagesService.uploadFile(file, projectId).subscribe({
        next: () => {
          completed++;
          if (completed === files.length) {
            this.isUploading = false;
            if (projectId) {
              this.openProject(this.currentNode!);
            } else {
              this.loadTree();
            }
          }
        },
        error: () => {
          completed++;
          if (completed === files.length) {
            this.isUploading = false;
            if (projectId) {
              this.openProject(this.currentNode!);
            } else {
              this.loadTree();
            }
          }
        }
      });
    }

    input.value = '';
  }

  onCancel(): void {
    this.dialogRef.close(null);
  }
}

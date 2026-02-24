import { Component, OnInit } from '@angular/core';
import { MatDialogRef } from '@angular/material/dialog';
import { PagesService } from '../../../services/pages.service';
import { ProjectInfo, ProjectDetail, PageInfo, SelectedPage } from '../../../models/pages';
import { environment } from '../../../../environments/environment';

@Component({
  selector: 'app-image-browser-dialog',
  templateUrl: './image-browser-dialog.component.html',
  styleUrls: ['./image-browser-dialog.component.scss']
})
export class ImageBrowserDialogComponent implements OnInit {
  projects: ProjectInfo[] = [];
  selectedProject: ProjectDetail | null = null;
  isLoading = false;
  isUploading = false;

  // Multi-select
  selectedPages: Set<number> = new Set();
  private lastSelectedIndex: number | null = null;

  constructor(
    public dialogRef: MatDialogRef<ImageBrowserDialogComponent>,
    private pagesService: PagesService
  ) {}

  ngOnInit(): void {
    this.loadProjects();
  }

  loadProjects(): void {
    this.isLoading = true;
    this.pagesService.getProjects().subscribe({
      next: (response) => {
        this.projects = response.projects;
        this.isLoading = false;
      },
      error: () => {
        this.isLoading = false;
      }
    });
  }

  openProject(project: ProjectInfo): void {
    this.isLoading = true;
    this.pagesService.getProject(project.project_id).subscribe({
      next: (detail) => {
        this.selectedProject = detail;
        this.isLoading = false;
      },
      error: () => {
        this.isLoading = false;
      }
    });
  }

  goBack(): void {
    this.selectedProject = null;
    this.selectedPages.clear();
    this.lastSelectedIndex = null;
  }

  getThumbnailUrl(page: PageInfo): string {
    return `${environment.apiUrl}${page.thumbnail_url}`;
  }

  selectPage(page: PageInfo, event: MouseEvent): void {
    if (!this.selectedProject) return;

    const pages = this.selectedProject.pages;
    const index = pages.indexOf(page);

    if (event.shiftKey && this.lastSelectedIndex !== null) {
      // Shift+click: select range
      const start = Math.min(this.lastSelectedIndex, index);
      const end = Math.max(this.lastSelectedIndex, index);
      for (let i = start; i <= end; i++) {
        this.selectedPages.add(pages[i].page_number);
      }
    } else if (event.ctrlKey || event.metaKey) {
      // Ctrl+click: toggle individual
      if (this.selectedPages.has(page.page_number)) {
        this.selectedPages.delete(page.page_number);
      } else {
        this.selectedPages.add(page.page_number);
      }
    } else {
      // Plain click: single select (for quick single pick, close immediately)
      const selected: SelectedPage = {
        project_id: this.selectedProject.project_id,
        project_name: this.selectedProject.name,
        page_number: page.page_number,
        filename: page.filename,
        image_url: `${environment.apiUrl}${page.full_url}`
      };
      this.dialogRef.close([selected]);
      return;
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

  onUploadFile(event: Event): void {
    const input = event.target as HTMLInputElement;
    if (!input.files || input.files.length === 0) return;

    this.isUploading = true;
    const file = input.files[0];
    this.pagesService.uploadFile(file).subscribe({
      next: () => {
        this.isUploading = false;
        this.loadProjects();
      },
      error: () => {
        this.isUploading = false;
      }
    });
    input.value = '';
  }

  onCancel(): void {
    this.dialogRef.close(null);
  }
}

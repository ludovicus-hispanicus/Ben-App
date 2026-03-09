import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import { ProjectListResponse, ProjectDetail, UploadResponse, ProjectTreeNode, ProjectInfo } from '../models/pages';

@Injectable({ providedIn: 'root' })
export class PagesService {
  private baseUrl = '/pages';

  constructor(private http: HttpClient) {}

  createProject(name: string, parentId?: string): Observable<UploadResponse> {
    const body: any = { name };
    if (parentId) { body.parent_id = parentId; }
    return this.http.post<UploadResponse>(
      `${environment.apiUrl}${this.baseUrl}/projects`,
      body
    );
  }

  getTree(): Observable<ProjectTreeNode[]> {
    return this.http.get<ProjectTreeNode[]>(
      `${environment.apiUrl}${this.baseUrl}/tree`
    );
  }

  getChildren(projectId: string): Observable<ProjectInfo[]> {
    return this.http.get<ProjectInfo[]>(
      `${environment.apiUrl}${this.baseUrl}/projects/${projectId}/children`
    );
  }

  getBreadcrumb(projectId: string): Observable<ProjectInfo[]> {
    return this.http.get<ProjectInfo[]>(
      `${environment.apiUrl}${this.baseUrl}/projects/${projectId}/breadcrumb`
    );
  }

  renameProject(projectId: string, name: string): Observable<any> {
    return this.http.patch(
      `${environment.apiUrl}${this.baseUrl}/projects/${projectId}/rename`,
      { name }
    );
  }

  moveProject(projectId: string, parentId: string | null): Observable<any> {
    return this.http.patch(
      `${environment.apiUrl}${this.baseUrl}/projects/${projectId}/move`,
      { parent_id: parentId }
    );
  }

  getPdfPageCount(file: File): Observable<{ page_count: number; filename: string }> {
    const formData = new FormData();
    formData.append('file', file, file.name);
    return this.http.post<{ page_count: number; filename: string }>(
      `${environment.apiUrl}${this.baseUrl}/pdf-page-count`, formData
    );
  }

  uploadPdf(file: File, projectName: string, pageFrom?: number, pageTo?: number, dpi?: number): Observable<UploadResponse> {
    const formData = new FormData();
    formData.append('file', file, file.name);
    formData.append('name', projectName);
    if (pageFrom != null) { formData.append('page_from', pageFrom.toString()); }
    if (pageTo != null) { formData.append('page_to', pageTo.toString()); }
    if (dpi != null) { formData.append('dpi', dpi.toString()); }
    return this.http.post<UploadResponse>(
      `${environment.apiUrl}${this.baseUrl}/upload`, formData
    );
  }

  uploadFile(file: File, projectId?: string, pageFrom?: number, pageTo?: number, dpi?: number): Observable<UploadResponse> {
    const formData = new FormData();
    formData.append('file', file, file.name);
    if (pageFrom != null) { formData.append('page_from', pageFrom.toString()); }
    if (pageTo != null) { formData.append('page_to', pageTo.toString()); }
    if (dpi != null) { formData.append('dpi', dpi.toString()); }
    const url = projectId
      ? `${environment.apiUrl}${this.baseUrl}/projects/${projectId}/upload`
      : `${environment.apiUrl}${this.baseUrl}/upload`;
    return this.http.post<UploadResponse>(url, formData);
  }

  getProjects(): Observable<ProjectListResponse> {
    return this.http.get<ProjectListResponse>(
      `${environment.apiUrl}${this.baseUrl}/projects`
    );
  }

  getProject(projectId: string): Observable<ProjectDetail> {
    return this.http.get<ProjectDetail>(
      `${environment.apiUrl}${this.baseUrl}/projects/${projectId}`
    );
  }

  getPageImageUrl(projectId: string, pageNumber: number): string {
    return `${environment.apiUrl}${this.baseUrl}/projects/${projectId}/image/${pageNumber}`;
  }

  getPageThumbnailUrl(projectId: string, pageNumber: number): string {
    return `${environment.apiUrl}${this.baseUrl}/projects/${projectId}/thumbnail/${pageNumber}`;
  }

  getFileUrl(projectId: string, filename: string): string {
    return `${environment.apiUrl}${this.baseUrl}/projects/${projectId}/file/${filename}`;
  }

  getImageBlob(url: string): Observable<Blob> {
    return this.http.get(url, { responseType: 'blob' });
  }

  deletePages(projectId: string, filenames: string[]): Observable<any> {
    return this.http.request('DELETE',
      `${environment.apiUrl}${this.baseUrl}/projects/${projectId}/pages`,
      { body: { filenames: filenames } }
    );
  }

  downloadProjectUrl(projectId: string): string {
    return `${environment.apiUrl}${this.baseUrl}/projects/${projectId}/download`;
  }

  deleteProject(projectId: string): Observable<any> {
    return this.http.delete(
      `${environment.apiUrl}${this.baseUrl}/projects/${projectId}`
    );
  }
}

import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { environment } from 'src/environments/environment';
import { Observable } from 'rxjs';
import { ProjectPreview, TextPreview } from '../models/cured';

@Injectable({ providedIn: 'root' })
export class ProjectService {
    public baseUrl = "/projects";
    constructor(private http: HttpClient) {}

    list(parentId?: number): Observable<ProjectPreview[]> {
        const params: any = {};
        if (parentId !== undefined) {
            params.parent_id = parentId.toString();
        }
        return this.http.get<ProjectPreview[]>(
            `${environment.apiUrl}${this.baseUrl}/list`,
            { params }
        );
    }

    getTree(): Observable<ProjectPreview[]> {
        return this.http.get<ProjectPreview[]>(
            `${environment.apiUrl}${this.baseUrl}/tree`
        );
    }

    create(name: string, parentId?: number): Observable<number> {
        return this.http.post<number>(
            `${environment.apiUrl}${this.baseUrl}/create`,
            { name, parent_id: parentId || null }
        );
    }

    rename(projectId: number, name: string) {
        return this.http.patch<{ updated: boolean }>(
            `${environment.apiUrl}${this.baseUrl}/${projectId}/rename`,
            { name }
        );
    }

    move(projectId: number, parentId: number | null) {
        return this.http.patch<{ updated: boolean }>(
            `${environment.apiUrl}${this.baseUrl}/${projectId}/move`,
            { parent_id: parentId }
        );
    }

    delete(projectId: number) {
        return this.http.delete<{ deleted: boolean }>(
            `${environment.apiUrl}${this.baseUrl}/${projectId}`
        );
    }

    getTexts(projectId: number): Observable<TextPreview[]> {
        return this.http.get<TextPreview[]>(
            `${environment.apiUrl}${this.baseUrl}/${projectId}/texts`
        );
    }

    getChildren(projectId: number): Observable<ProjectPreview[]> {
        return this.http.get<ProjectPreview[]>(
            `${environment.apiUrl}${this.baseUrl}/${projectId}/children`
        );
    }

    getBreadcrumb(projectId: number): Observable<ProjectPreview[]> {
        return this.http.get<ProjectPreview[]>(
            `${environment.apiUrl}${this.baseUrl}/${projectId}/breadcrumb`
        );
    }

    getUnassignedTexts(): Observable<TextPreview[]> {
        return this.http.get<TextPreview[]>(
            `${environment.apiUrl}${this.baseUrl}/unassigned/texts`
        );
    }

    assignText(textId: number, projectId: number | null): Observable<{ updated: boolean }> {
        return this.http.patch<{ updated: boolean }>(
            `${environment.apiUrl}${this.baseUrl}/texts/${textId}/assign`,
            { project_id: projectId }
        );
    }

    exportProject(projectId: number, format: string): Observable<Blob> {
        return this.http.get(
            `${environment.apiUrl}${this.baseUrl}/${projectId}/export`,
            { params: { format }, responseType: 'blob' }
        );
    }

    exportSingleText(textId: number, format: string = 'txt'): Observable<Blob> {
        return this.http.get(
            `${environment.apiUrl}${this.baseUrl}/texts/${textId}/export`,
            { params: { format }, responseType: 'blob' }
        );
    }
}

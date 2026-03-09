import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { environment } from 'src/environments/environment';
import { Observable } from 'rxjs';
import { DatasetPreview, TextPreview } from '../models/cured';

@Injectable({ providedIn: 'root' })
export class DatasetService {
    public baseUrl = "/datasets";
    constructor(private http: HttpClient) {}

    list(parentId?: number): Observable<DatasetPreview[]> {
        const params: any = {};
        if (parentId !== undefined) {
            params.parent_id = parentId.toString();
        }
        return this.http.get<DatasetPreview[]>(
            `${environment.apiUrl}${this.baseUrl}/list`,
            { params }
        );
    }

    getTree(): Observable<DatasetPreview[]> {
        return this.http.get<DatasetPreview[]>(
            `${environment.apiUrl}${this.baseUrl}/tree`
        );
    }

    create(name: string, parentId?: number): Observable<number> {
        return this.http.post<number>(
            `${environment.apiUrl}${this.baseUrl}/create`,
            { name, parent_id: parentId || null }
        );
    }

    rename(datasetId: number, name: string) {
        return this.http.patch<{ updated: boolean }>(
            `${environment.apiUrl}${this.baseUrl}/${datasetId}/rename`,
            { name }
        );
    }

    move(datasetId: number, parentId: number | null) {
        return this.http.patch<{ updated: boolean }>(
            `${environment.apiUrl}${this.baseUrl}/${datasetId}/move`,
            { parent_id: parentId }
        );
    }

    delete(datasetId: number) {
        return this.http.delete<{ deleted: boolean }>(
            `${environment.apiUrl}${this.baseUrl}/${datasetId}`
        );
    }

    getTexts(datasetId: number): Observable<TextPreview[]> {
        return this.http.get<TextPreview[]>(
            `${environment.apiUrl}${this.baseUrl}/${datasetId}/texts`
        );
    }

    getChildren(datasetId: number): Observable<DatasetPreview[]> {
        return this.http.get<DatasetPreview[]>(
            `${environment.apiUrl}${this.baseUrl}/${datasetId}/children`
        );
    }

    getBreadcrumb(datasetId: number): Observable<DatasetPreview[]> {
        return this.http.get<DatasetPreview[]>(
            `${environment.apiUrl}${this.baseUrl}/${datasetId}/breadcrumb`
        );
    }

    getUnassignedTexts(): Observable<TextPreview[]> {
        return this.http.get<TextPreview[]>(
            `${environment.apiUrl}${this.baseUrl}/unassigned/texts`
        );
    }

    assignText(textId: number, datasetId: number | null): Observable<{ updated: boolean }> {
        return this.http.patch<{ updated: boolean }>(
            `${environment.apiUrl}${this.baseUrl}/texts/${textId}/assign`,
            { dataset_id: datasetId }
        );
    }

    exportDataset(datasetId: number, format: string): Observable<Blob> {
        return this.http.get(
            `${environment.apiUrl}${this.baseUrl}/${datasetId}/export`,
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

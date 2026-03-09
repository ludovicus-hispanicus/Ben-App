import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from 'src/environments/environment';
import {
    CuReClassifyResponse,
    CuReDetectResponse,
    CuReCropClassifyResponse,
    CuReModelInfo,
    CuReActiveModel,
    CuReTrainingStatus,
    CuReTrainingProgress,
    CuReAnnotationStats,
} from '../models/cure';
import { DatasetPreview } from '../models/cured';

@Injectable({ providedIn: 'root' })
export class CureService {
    public baseUrl = '/cure';

    constructor(private http: HttpClient) {}

    // ==========================================
    // Datasets (CuRe annotation datasets)
    // ==========================================

    listDatasets(): Observable<DatasetPreview[]> {
        return this.http.get<DatasetPreview[]>(
            `${environment.apiUrl}${this.baseUrl}/datasets/list`
        );
    }

    createDataset(name: string): Observable<number> {
        return this.http.post<number>(
            `${environment.apiUrl}${this.baseUrl}/datasets/create`,
            { name }
        );
    }

    renameDataset(datasetId: number, name: string): Observable<{ updated: boolean }> {
        return this.http.patch<{ updated: boolean }>(
            `${environment.apiUrl}${this.baseUrl}/datasets/${datasetId}/rename`,
            { name }
        );
    }

    deleteDataset(datasetId: number): Observable<{ deleted: boolean }> {
        return this.http.delete<{ deleted: boolean }>(
            `${environment.apiUrl}${this.baseUrl}/datasets/${datasetId}`
        );
    }

    // ==========================================
    // Inference
    // ==========================================

    classify(imageBase64: string, model: string = 'active'): Observable<CuReClassifyResponse> {
        return this.http.post<CuReClassifyResponse>(
            `${environment.apiUrl}${this.baseUrl}/classify`,
            { image: imageBase64, model }
        );
    }

    detect(imageBase64: string): Observable<CuReDetectResponse> {
        return this.http.post<CuReDetectResponse>(
            `${environment.apiUrl}${this.baseUrl}/detect`,
            { image: imageBase64 }
        );
    }

    classifyCrop(imageBase64: string, model: string = 'active', topK: number = 3): Observable<CuReCropClassifyResponse> {
        return this.http.post<CuReCropClassifyResponse>(
            `${environment.apiUrl}${this.baseUrl}/classify-crop`,
            { image: imageBase64, model, top_k: topK }
        );
    }

    // ==========================================
    // Model management
    // ==========================================

    getModels(): Observable<{ models: CuReModelInfo[]; active_model: string }> {
        return this.http.get<{ models: CuReModelInfo[]; active_model: string }>(
            `${environment.apiUrl}${this.baseUrl}/models`
        );
    }

    getActiveModel(): Observable<CuReActiveModel> {
        return this.http.get<CuReActiveModel>(
            `${environment.apiUrl}${this.baseUrl}/models/active`
        );
    }

    activateModel(modelName: string): Observable<{ message: string; model_name: string }> {
        return this.http.post<{ message: string; model_name: string }>(
            `${environment.apiUrl}${this.baseUrl}/models/${modelName}/activate`,
            null
        );
    }

    deleteModel(modelName: string): Observable<{ message: string }> {
        return this.http.delete<{ message: string }>(
            `${environment.apiUrl}${this.baseUrl}/models/${modelName}`
        );
    }

    // ==========================================
    // Training
    // ==========================================

    getTrainingStatus(): Observable<CuReTrainingStatus> {
        return this.http.get<CuReTrainingStatus>(
            `${environment.apiUrl}${this.baseUrl}/training/status`
        );
    }

    startTraining(params: {
        epochs?: number;
        model_name?: string;
        batch_size?: number;
        learning_rate?: number;
        patience?: number;
        device?: string;
        base_model?: string;
    }): Observable<{ message: string; model_name: string; epochs: number }> {
        return this.http.post<{ message: string; model_name: string; epochs: number }>(
            `${environment.apiUrl}${this.baseUrl}/training/start`,
            params
        );
    }

    getTrainingProgress(): Observable<CuReTrainingProgress> {
        return this.http.get<CuReTrainingProgress>(
            `${environment.apiUrl}${this.baseUrl}/training/progress`
        );
    }

    cancelTraining(): Observable<{ message: string }> {
        return this.http.post<{ message: string }>(
            `${environment.apiUrl}${this.baseUrl}/training/cancel`,
            null
        );
    }

    // ==========================================
    // Training data management
    // ==========================================

    uploadAnnotations(imageBase64: string, annotationsCsv: string, imageName?: string): Observable<any> {
        const body: any = { image: imageBase64, annotations_csv: annotationsCsv };
        if (imageName) {
            body.image_name = imageName;
        }
        return this.http.post(
            `${environment.apiUrl}${this.baseUrl}/annotations/upload`,
            body
        );
    }

    getAnnotationStats(): Observable<CuReAnnotationStats> {
        return this.http.get<CuReAnnotationStats>(
            `${environment.apiUrl}${this.baseUrl}/annotations/stats`
        );
    }

    getLabels(): Observable<{ labels: string[]; label_to_unicode: { [key: string]: string }; num_classes: number }> {
        return this.http.get<{ labels: string[]; label_to_unicode: { [key: string]: string }; num_classes: number }>(
            `${environment.apiUrl}${this.baseUrl}/labels`
        );
    }

    uploadLabels(csvContent: string): Observable<{ message: string; count: number }> {
        return this.http.post<{ message: string; count: number }>(
            `${environment.apiUrl}${this.baseUrl}/labels/upload`,
            { csv_content: csvContent }
        );
    }

    // ==========================================
    // PDF conversion (reuse CuReD endpoint)
    // ==========================================

    convertPdf(pdf: File, page: number): Observable<Blob> {
        const uploadData = new FormData();
        uploadData.append('raw_pdf', pdf, 'pdf');
        uploadData.append('page', page.toString());
        return this.http.post(
            `${environment.apiUrl}/cured/convertPdf/`,
            uploadData,
            { responseType: 'blob' }
        );
    }
}

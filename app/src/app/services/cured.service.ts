
import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';

import { environment } from 'src/environments/environment';
import { Observable } from 'rxjs';
import { CuredResult, Dimensions, LetterDto } from '../models/letter';
import { SelectedPdf } from '../components/cure-d/cured.component';
import { CuredTransliterationData, CuredTransliterationPreview } from '../models/cured';


@Injectable({ providedIn: 'root' })
export class CuredService {
    public baseUrl = "/cured"
    public _cachedLabels = null;
    constructor(private http: HttpClient) { }


    convertPdf(pdf: SelectedPdf): Observable<Blob> {
        const uploadData = new FormData();
        uploadData.append('raw_pdf', pdf.pdf, "pdf");
        uploadData.append('page', pdf.page.toString());

        return this.http.post(`${environment.apiUrl}${this.baseUrl}/convertPdf/`,
                                     uploadData,
                                     {responseType: 'blob'});
    }

    getTransliterations(imageBase64: string, model: string = 'latest') {
        return this.http.post<CuredResult>(`${environment.apiUrl}${this.baseUrl}/getTransliterations`, {"image": imageBase64, "model": model});
    }

    getTextTransliterations(benId: number) {
        return this.http.get<CuredTransliterationPreview[]>(`${environment.apiUrl}${this.baseUrl}/${benId}/transliterations`);
    }

    loadTransliteration(textId: number, transliterationId: number) {
        return this.http.get<CuredTransliterationData>(`${environment.apiUrl}${this.baseUrl}/transliteration/${textId}/${transliterationId}`);
    }

    saveImage(file: File, textId: number) {
        let url = "/saveImage/";
        
        const uploadData = new FormData();
        uploadData.append('file', file, file.name);
        uploadData.append('text_id', textId.toString());

        
        return this.http.post<string>(`${environment.apiUrl}${this.baseUrl}${url}`, uploadData);
    }

    createSubmission(textId: number, transliterationId: number, lines: string[], boxes: Dimensions[], imageName: string, isFixed: boolean) {
        return this.http.post<number>(`${environment.apiUrl}${this.baseUrl}/createSubmission`,
        {
            "text_id": textId,
            "transliteration_id": transliterationId,
            "lines": lines,
            "boxes": boxes,
            "image_name": imageName,
            "is_fixed": isFixed
        });
    }

    getImage(textId: number, transliterationId: number): Observable<Blob> {
        return this.http.get(`${environment.apiUrl}${this.baseUrl}/transliterationImage/${textId}/${transliterationId}`, { responseType: 'blob' });
    }

    deleteTransliteration(textId: number, transliterationId: number) {
        return this.http.delete<{deleted: string}>(`${environment.apiUrl}${this.baseUrl}/${textId}/${transliterationId}`);
    }

    deleteText(textId: number) {
        return this.http.delete<{deleted: string}>(`${environment.apiUrl}${this.baseUrl}/${textId}`);
    }

    getTrainingStatus() {
        return this.http.get<{
            curatedTexts: number;
            previousLines: number;
            newLines: number;
            totalLines: number;
            requiredForNextTraining: number;
            progress: number;
            isReady: boolean;
            lastTraining: string | null;
            currentTraining: TrainingProgress | null;
        }>(`${environment.apiUrl}${this.baseUrl}/training/status`);
    }

    startTraining(epochs: number = 50, modelName: string = null) {
        const params: any = { epochs };
        if (modelName) {
            params.model_name = modelName;
        }
        return this.http.post<{ message: string; epochs: number; model_name: string }>(
            `${environment.apiUrl}${this.baseUrl}/training/start`,
            null,
            { params }
        );
    }

    getTrainingProgress() {
        return this.http.get<TrainingProgress>(`${environment.apiUrl}${this.baseUrl}/training/progress`);
    }

    cancelTraining() {
        return this.http.post<{ message: string }>(`${environment.apiUrl}${this.baseUrl}/training/cancel`, null);
    }

    listModels() {
        return this.http.get<{ models: TrainedModel[] }>(`${environment.apiUrl}${this.baseUrl}/training/models`);
    }

    getActiveModel() {
        return this.http.get<ActiveModelInfo>(`${environment.apiUrl}${this.baseUrl}/training/active-model`);
    }

    activateModel(modelName: string) {
        return this.http.post<{ message: string }>(
            `${environment.apiUrl}${this.baseUrl}/training/models/${modelName}/activate`,
            null
        );
    }

    applyPostProcessing(lines: string[]) {
        return this.http.post<PostProcessingResult>(
            `${environment.apiUrl}${this.baseUrl}/postprocessor/apply`,
            { lines }
        );
    }

}

export interface PostProcessingResult {
    lines: string[];
    corrections: PostProcessingCorrection[];
}

export interface PostProcessingCorrection {
    original: string;
    corrected: string;
    corrections_count: number;
    corrections: Array<{
        original: string;
        corrected: string;
        rule_type: string;
        description: string;
        position: number;
    }>;
}

export interface TrainingProgress {
    status: 'idle' | 'preparing' | 'training' | 'completed' | 'failed' | 'cancelled';
    current_epoch: number;
    total_epochs: number;
    accuracy: number;
    model_name: string | null;
    error: string | null;
    started_at: string | null;
    completed_at: string | null;
}

export interface TrainedModel {
    name: string;
    path: string;
    created: string;
    epochs?: number;
    accuracy?: number;
    size_mb?: number;
}

export interface ActiveModelInfo {
    name: string;
    is_pretrained: boolean;
    size_mb: number;
    last_modified: string | null;
}
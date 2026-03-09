
import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';

import { environment } from 'src/environments/environment';
import { Observable } from 'rxjs';
import { CuredResult, Dimensions, LetterDto, TeiValidationResult, TeiEntryResult, TeiValidationError } from '../models/letter';
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

    getTransliterations(
        imageBase64: string,
        model: string = 'latest',
        prompt: string = 'dictionary',
        apiKey?: string,
        teiOptions?: { teiModel: string; teiProvider: string; teiApiKey?: string },
        correctionRules?: string
    ) {
        const body: any = {
            "image": imageBase64,
            "model": model,
            "prompt": prompt
        };
        if (apiKey) {
            body.apiKey = apiKey;
        }
        if (teiOptions) {
            body.teiModel = teiOptions.teiModel;
            body.teiProvider = teiOptions.teiProvider;
            if (teiOptions.teiApiKey) {
                body.teiApiKey = teiOptions.teiApiKey;
            }
        }
        if (correctionRules) {
            body.correctionRules = correctionRules;
        }
        return this.http.post<CuredResult>(`${environment.apiUrl}${this.baseUrl}/getTransliterations`, body);
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

    createSubmission(textId: number, transliterationId: number, lines: string[], boxes: Dimensions[], imageName: string, isCuratedKraken: boolean = false, isCuratedVlm: boolean = false) {
        const body: any = {
            "text_id": textId,
            "transliteration_id": transliterationId,
            "lines": lines,
            "boxes": boxes,
            "image_name": imageName,
            "is_curated_kraken": isCuratedKraken,
            "is_curated_vlm": isCuratedVlm
        };
        return this.http.post<number>(`${environment.apiUrl}${this.baseUrl}/createSubmission`, body);
    }

    getImage(textId: number, transliterationId: number): Observable<Blob> {
        const cacheBust = Date.now();
        return this.http.get(`${environment.apiUrl}${this.baseUrl}/transliterationImage/${textId}/${transliterationId}?t=${cacheBust}`, { responseType: 'blob' });
    }

    deleteTransliteration(textId: number, transliterationId: number) {
        return this.http.delete<{deleted: string}>(`${environment.apiUrl}${this.baseUrl}/${textId}/${transliterationId}`);
    }

    deleteText(textId: number) {
        return this.http.delete<{deleted: string}>(`${environment.apiUrl}${this.baseUrl}/${textId}`);
    }

    batchDeleteTexts(textIds: number[]): Observable<{ deleted: number; errors: any[] }> {
        return this.http.post<{ deleted: number; errors: any[] }>(
            `${environment.apiUrl}${this.baseUrl}/batch-delete`,
            { text_ids: textIds }
        );
    }

    removeTileMarkers(datasetId?: number, textIds?: number[]): Observable<{ cleaned: number; total_markers_removed: number }> {
        return this.http.post<{ cleaned: number; total_markers_removed: number }>(
            `${environment.apiUrl}${this.baseUrl}/remove-tile-markers`,
            { dataset_id: datasetId || null, text_ids: textIds || null }
        );
    }

    batchCurate(textIds: number[], curate: boolean, target: string = 'both') {
        return this.http.patch<{ updated: number; skipped: number; errors: any[] }>(
            `${environment.apiUrl}${this.baseUrl}/batch-curate`,
            { text_ids: textIds, curate, target }
        );
    }

    getCuratedStats(datasetId?: number) {
        let url = `${environment.apiUrl}${this.baseUrl}/training/curated-stats`;
        if (datasetId) url += `?dataset_id=${datasetId}`;
        return this.http.get<{
            total: { lines: number; texts: number };
            kraken: { lines: number; texts: number };
            vlm: { lines: number; texts: number };
        }>(url);
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

    startTraining(epochs: number = 50, modelName: string = null, baseModel: string = null) {
        const params: any = { epochs };
        if (modelName) {
            params.model_name = modelName;
        }
        if (baseModel) {
            params.base_model = baseModel;
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

    getBaseModelsMetadata() {
        return this.http.get<{ [key: string]: BaseModelMetadata }>(`${environment.apiUrl}${this.baseUrl}/training/base-models`);
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

    getAvailableOcrModels() {
        return this.http.get<{ models: OcrModelOption[] }>(
            `${environment.apiUrl}${this.baseUrl}/available-models`
        );
    }

    getOllamaModels(): Observable<string[]> {
        return this.http.get<string[]>(`${environment.apiUrl}${this.baseUrl}/ollama/models`);
    }

    // ==========================================
    // Kraken OCR Training Methods
    // ==========================================

    getKrakenTrainingStatus(datasetIds?: number[]) {
        let url = `${environment.apiUrl}${this.baseUrl}/training/kraken/status`;
        if (datasetIds && datasetIds.length > 0) {
            const qs = datasetIds.map(id => `dataset_ids=${id}`).join('&');
            url += `?${qs}`;
        }
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
        }>(url);
    }

    startKrakenTraining(epochs: number = 500, modelName: string = null, baseModel: string = null, batchSize: number = 1, device: string = 'auto', patience: number = 10, datasetIds?: number[]) {
        const params: any = { epochs, device, patience };
        if (modelName) {
            params.model_name = modelName;
        }
        if (baseModel && baseModel !== 'from_scratch') {
            params.base_model = baseModel;
        }
        if (batchSize > 1) {
            params.batch_size = batchSize;
        }
        if (datasetIds && datasetIds.length > 0) {
            params.dataset_ids = datasetIds;
        }
        return this.http.post<{ message: string; epochs: number; model_name: string }>(
            `${environment.apiUrl}${this.baseUrl}/training/kraken/start`,
            null,
            { params }
        );
    }

    getKrakenTrainingProgress() {
        return this.http.get<TrainingProgress>(`${environment.apiUrl}${this.baseUrl}/training/kraken/progress`);
    }

    cancelKrakenTraining() {
        return this.http.post<{ message: string }>(`${environment.apiUrl}${this.baseUrl}/training/kraken/cancel`, null);
    }

    listKrakenModels() {
        return this.http.get<{ models: TrainedModel[] }>(`${environment.apiUrl}${this.baseUrl}/training/kraken/models`);
    }

    getKrakenActiveModel() {
        return this.http.get<ActiveModelInfo>(`${environment.apiUrl}${this.baseUrl}/training/kraken/active-model`);
    }

    activateKrakenModel(modelName: string) {
        return this.http.post<{ message: string }>(
            `${environment.apiUrl}${this.baseUrl}/training/kraken/models/${modelName}/activate`,
            null
        );
    }

    deleteKrakenModel(modelName: string) {
        return this.http.delete<{ message: string }>(
            `${environment.apiUrl}${this.baseUrl}/training/kraken/models/${modelName}`
        );
    }

    getKrakenBaseModels() {
        return this.http.get<{ models: BaseModelOption[] }>(
            `${environment.apiUrl}${this.baseUrl}/training/kraken/base-models`
        );
    }

    // ==========================================
    // Qwen3-VL QLoRA Training Methods
    // ==========================================

    getQwenTrainingStatus(datasetIds?: number[]) {
        let url = `${environment.apiUrl}${this.baseUrl}/training/qwen/status`;
        if (datasetIds && datasetIds.length > 0) {
            const qs = datasetIds.map(id => `dataset_ids=${id}`).join('&');
            url += `?${qs}`;
        }
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
        }>(url);
    }

    startQwenTraining(epochs: number = 10, modelName: string = null, baseModel: string = null, outputMode: string = 'plain', device: string = 'auto', patience: number = 3, datasetIds?: number[]) {
        const params: any = { epochs, output_mode: outputMode, device, patience };
        if (modelName) {
            params.model_name = modelName;
        }
        if (baseModel) {
            params.base_model = baseModel;
        }
        if (datasetIds && datasetIds.length > 0) {
            params.dataset_ids = datasetIds;
        }
        return this.http.post<{ message: string; epochs: number; model_name: string; base_model: string; output_mode: string }>(
            `${environment.apiUrl}${this.baseUrl}/training/qwen/start`,
            null,
            { params }
        );
    }

    getQwenTrainingProgress() {
        return this.http.get<TrainingProgress>(`${environment.apiUrl}${this.baseUrl}/training/qwen/progress`);
    }

    cancelQwenTraining() {
        return this.http.post<{ message: string }>(`${environment.apiUrl}${this.baseUrl}/training/qwen/cancel`, null);
    }

    listQwenModels() {
        return this.http.get<{ models: TrainedModel[] }>(`${environment.apiUrl}${this.baseUrl}/training/qwen/models`);
    }

    getQwenActiveModel() {
        return this.http.get<ActiveModelInfo>(`${environment.apiUrl}${this.baseUrl}/training/qwen/active-model`);
    }

    activateQwenModel(modelName: string) {
        return this.http.post<{ message: string }>(
            `${environment.apiUrl}${this.baseUrl}/training/qwen/models/${modelName}/activate`,
            null
        );
    }

    deleteQwenModel(modelName: string) {
        return this.http.delete<{ message: string }>(
            `${environment.apiUrl}${this.baseUrl}/training/qwen/models/${modelName}`
        );
    }

    getQwenOutputModes() {
        return this.http.get<{ modes: { [key: string]: string } }>(
            `${environment.apiUrl}${this.baseUrl}/training/qwen/output-modes`
        );
    }

    getQwenBaseModels() {
        return this.http.get<{ models: { id: string; name: string; hf_id: string }[] }>(
            `${environment.apiUrl}${this.baseUrl}/training/qwen/base-models`
        );
    }

    // ========== TrOCR Training ==========

    getTrOCRTrainingStatus(datasetIds?: number[]) {
        let url = `${environment.apiUrl}${this.baseUrl}/training/trocr/status`;
        if (datasetIds && datasetIds.length > 0) {
            const qs = datasetIds.map(id => `dataset_ids=${id}`).join('&');
            url += `?${qs}`;
        }
        return this.http.get<{
            curatedTexts: number;
            previousLines: number;
            newLines: number;
            totalLines: number;
            requiredForNextTraining: number;
            progress: number;
            isReady: boolean;
            lastTraining: string | null;
            currentTraining: any | null;
        }>(url);
    }

    startTrOCRTraining(epochs: number = 30, modelName: string = null, baseModel: string = null, device: string = 'auto', patience: number = 5, learningRate: number = 0.00005, freezeEncoder: boolean = false, datasetIds?: number[]) {
        const params: any = { epochs, device, patience, learning_rate: learningRate, freeze_encoder: freezeEncoder };
        if (modelName) params.model_name = modelName;
        if (baseModel) params.base_model = baseModel;
        if (datasetIds && datasetIds.length > 0) params.dataset_ids = datasetIds;
        return this.http.post<{ message: string; epochs: number; model_name: string; base_model: string }>(
            `${environment.apiUrl}${this.baseUrl}/training/trocr/start`, null, { params }
        );
    }

    getTrOCRTrainingProgress() {
        return this.http.get<any>(`${environment.apiUrl}${this.baseUrl}/training/trocr/progress`);
    }

    cancelTrOCRTraining() {
        return this.http.post<{ message: string }>(`${environment.apiUrl}${this.baseUrl}/training/trocr/cancel`, null);
    }

    listTrOCRModels() {
        return this.http.get<{ models: TrainedModel[] }>(`${environment.apiUrl}${this.baseUrl}/training/trocr/models`);
    }

    getTrOCRActiveModel() {
        return this.http.get<ActiveModelInfo>(`${environment.apiUrl}${this.baseUrl}/training/trocr/active-model`);
    }

    activateTrOCRModel(modelName: string) {
        return this.http.post<{ message: string }>(
            `${environment.apiUrl}${this.baseUrl}/training/trocr/models/${modelName}/activate`, null
        );
    }

    deleteTrOCRModel(modelName: string) {
        return this.http.delete<{ message: string }>(
            `${environment.apiUrl}${this.baseUrl}/training/trocr/models/${modelName}`
        );
    }

    getTrOCRBaseModels() {
        return this.http.get<{ models: { id: string; name: string; hf_id: string; params: string }[] }>(
            `${environment.apiUrl}${this.baseUrl}/training/trocr/base-models`
        );
    }

    // ==========================================
    // Museum Data Methods
    // ==========================================

    /**
     * Get museum abbreviations and full names.
     * Returns a map of abbreviation -> full description.
     */
    getMuseums(): Observable<{ [key: string]: string }> {
        return this.http.get<{ [key: string]: string }>(
            `${environment.apiUrl}${this.baseUrl}/museums`
        );
    }

    // ==========================================
    // Line Detection (Kraken segmentation only)
    // ==========================================

    /**
     * Detect line bounding boxes using Kraken segmentation (no OCR).
     * Used to get bounding boxes for training data when using non-Kraken OCR models.
     */
    detectLines(imageBase64: string) {
        return this.http.post<{ dimensions: Dimensions[]; error?: string }>(
            `${environment.apiUrl}${this.baseUrl}/detectLines`,
            { image: imageBase64 }
        );
    }

    // ==========================================
    // TEI Lex-0 Validation Methods
    // ==========================================

    /**
     * Validate a TEI Lex-0 entry against XSD + custom rules.
     */
    validateTei(xml: string) {
        return this.http.post<TeiValidationResult>(
            `${environment.apiUrl}${this.baseUrl}/validate-tei`,
            { xml }
        );
    }

    /**
     * Retry a failed TEI entry with correction prompt via VLM.
     */
    retryTeiEntry(xml: string, errors: TeiValidationError[], provider: string, apiKey?: string) {
        const body: any = { xml, errors, provider };
        if (apiKey) {
            body.apiKey = apiKey;
        }
        return this.http.post<TeiEntryResult>(
            `${environment.apiUrl}${this.baseUrl}/retry-tei`,
            body
        );
    }

    // ==========================================
    // Translation Lookup Methods
    // ==========================================

    /**
     * Find a translation for a given museum number.
     * Translations are texts with label="translation" that share the same museum number.
     */
    findTranslation(museumName: string, museumNumber: number) {
        return this.http.get<TranslationLookupResult>(
            `${environment.apiUrl}${this.baseUrl}/translation/find`,
            { params: { museum_name: museumName, museum_number: museumNumber.toString() } }
        );
    }

    /**
     * Find the transliteration linked to a translation by museum number.
     * Used when viewing a translation to navigate to its source text.
     */
    findTransliteration(museumName: string, museumNumber: number) {
        return this.http.get<TransliterationLookupResult>(
            `${environment.apiUrl}${this.baseUrl}/transliteration/find`,
            { params: { museum_name: museumName, museum_number: museumNumber.toString() } }
        );
    }

    // ==========================================
    // CuReD Dataset Import / Export
    // ==========================================

    exportDatasetCured(datasetId: number): void {
        window.open(
            `${environment.apiUrl}${this.baseUrl}/export/dataset/${datasetId}`,
            '_blank'
        );
    }

    exportTextCured(textId: number): void {
        window.open(
            `${environment.apiUrl}${this.baseUrl}/export/text/${textId}`,
            '_blank'
        );
    }

    importCuredFolder(folderPath: string, datasetId?: number): Observable<{ imported: number; skipped: number; errors: any[] }> {
        const body: any = { folder_path: folderPath };
        if (datasetId != null) {
            body.dataset_id = datasetId;
        }
        return this.http.post<{ imported: number; skipped: number; errors: any[] }>(
            `${environment.apiUrl}${this.baseUrl}/import-folder`,
            body
        );
    }

    importCuredZip(file: File, datasetId?: number): Observable<{ imported: number; skipped: number; errors: any[] }> {
        const formData = new FormData();
        formData.append('file', file, file.name);
        if (datasetId != null) {
            formData.append('dataset_id', datasetId.toString());
        }
        return this.http.post<{ imported: number; skipped: number; errors: any[] }>(
            `${environment.apiUrl}${this.baseUrl}/import`,
            formData
        );
    }
}

export interface TrainingProgress {
    status: 'idle' | 'preparing' | 'training' | 'completed' | 'failed' | 'cancelled';
    current_epoch: number;
    total_epochs: number;
    accuracy: number;
    val_accuracy: number;
    loss: number;
    model_name: string | null;
    error: string | null;
    started_at: string | null;
    completed_at: string | null;
    epoch_history: EpochRecord[];
    best_accuracy: number;
    no_improve_count: number;
    early_stopped: boolean;
}

export interface EpochRecord {
    epoch: number;
    accuracy: number;
    val_accuracy: number;
    loss: number;
}

export interface OcrModelOption {
    value: string;
    label: string;
    is_custom: boolean;
}

export interface TrainedModel {
    name: string;
    path: string;
    created: string;
    epochs?: number;
    accuracy?: number;
    word_accuracy?: number;
    charset_size?: number;
    learning_rate?: number;
    size_mb?: number;
    base_model?: string;
    output_mode?: string;
    best_loss?: number;
    best_accuracy?: number;
    final_accuracy?: number;
    final_val_accuracy?: number;
    final_val_loss?: number;
    type?: string;
    epochs_trained?: number;
    early_stopped?: boolean;
}

export interface ActiveModelInfo {
    name: string;
    is_pretrained: boolean;
    size_mb: number;
    last_modified: string | null;
}

export interface BaseModelMetadata {
    size_mb: number;
    best_accuracy: number;
    last_accuracy: number;
    completed_epochs: number;
    alphabet_size: number;
}

export interface BaseModelOption {
    id: string;
    name: string;
    description: string;
}

export interface TranslationLookupResult {
    found: boolean;
    text_id?: number;
    transliteration_id?: number;
    museum_name?: string;
    museum_number?: number;
    lines?: string[];
    error?: string;
}

export interface TransliterationLookupResult {
    found: boolean;
    text_id?: number;
    transliteration_id?: number;
    museum_name?: string;
    museum_number?: number;
    error?: string;
}
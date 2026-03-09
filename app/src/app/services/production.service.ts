import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from 'src/environments/environment';

export interface GroupedText {
    identifier: string;
    identifier_type: string;
    parts: PartInfo[];
    has_production_text: boolean;
    production_id: number | null;
    is_exported: boolean;
}

export interface PartInfo {
    text_id: number;
    part: string;
    transliteration_id: number;
    is_curated: boolean;
    lines_count: number;
    last_modified: string;
    labels: string[];
    label: string;
    dataset_id: number | null;
}

export interface SourceTextReference {
    text_id: number;
    transliteration_id: number;
    part: string;
    image_name: string;
}

export interface ProductionEdit {
    content: string;
    time: string;
    user_id: string;
}

export interface UploadedImage {
    image_id: string;
    image_name: string;
    label: string;
    uploaded_at: string;
}

export interface ProductionText {
    production_id: number;
    identifier: string;
    identifier_type: string;
    source_texts: SourceTextReference[];
    uploaded_images: UploadedImage[];
    content: string;
    translation_content?: string;
    edit_history: ProductionEdit[];
    created_at: string;
    last_modified: string;
    uploader_id: string;
    notes: string;
}

export interface SourceTextContent {
    text_id: number;
    transliteration_id: number;
    part: string;
    lines: string[];
    image_name: string;
    label?: string;  // empty for transliterations
}

export interface TranslationContent {
    text_id: number;
    transliteration_id: number;
    part: string;
    lines: string[];
    label: string;  // "translation"
}

export interface ProductionSourcesResponse {
    sources: SourceTextContent[];
    translations: TranslationContent[];
}

export interface KwicResult {
    text_id: number;
    identifier: string;
    identifier_type: string;
    part: string;
    line_index: number;
    line_before: string | null;
    matching_line: string;
    line_after: string | null;
}

@Injectable({ providedIn: 'root' })
export class ProductionService {
    private baseUrl = '/production';

    constructor(private http: HttpClient) {}

    /**
     * Get all training data grouped by identifier (Museum number, P-number, Publication).
     * This is the main view for the CuReD dashboard.
     */
    getGroupedData(): Observable<GroupedText[]> {
        return this.http.get<GroupedText[]>(`${environment.apiUrl}${this.baseUrl}/grouped`);
    }

    /**
     * Get a production text by ID.
     */
    getProductionText(productionId: number): Observable<ProductionText> {
        return this.http.get<ProductionText>(`${environment.apiUrl}${this.baseUrl}/text/${productionId}`);
    }

    /**
     * Get the source texts (parts) for a production text with their content.
     * Returns sources (transliterations with images) and translations (text only).
     * Translations are automatically synced - no manual sync needed.
     */
    getProductionSources(productionId: number): Observable<ProductionSourcesResponse> {
        return this.http.get<ProductionSourcesResponse>(`${environment.apiUrl}${this.baseUrl}/text/${productionId}/sources`);
    }

    /**
     * Create a new production text from training data parts.
     */
    createProductionText(
        identifier: string,
        identifierType: string,
        sourceTextIds: number[],
        initialContent?: string
    ): Observable<ProductionText> {
        return this.http.post<ProductionText>(`${environment.apiUrl}${this.baseUrl}/text`, {
            identifier,
            identifier_type: identifierType,
            source_text_ids: sourceTextIds,
            initial_content: initialContent || ''
        });
    }

    /**
     * Update the content of a production text.
     */
    updateProductionText(productionId: number, content: string, translationContent?: string): Observable<ProductionText> {
        return this.http.put<ProductionText>(`${environment.apiUrl}${this.baseUrl}/text/${productionId}`, {
            content,
            translation_content: translationContent
        });
    }

    /**
     * Regenerate the production text content from source texts.
     */
    regenerateProductionContent(productionId: number): Observable<ProductionText> {
        return this.http.post<ProductionText>(`${environment.apiUrl}${this.baseUrl}/text/${productionId}/regenerate`, {});
    }


    /**
     * Delete a production text.
     */
    deleteProductionText(productionId: number): Observable<{ deleted: boolean }> {
        return this.http.delete<{ deleted: boolean }>(`${environment.apiUrl}${this.baseUrl}/text/${productionId}`);
    }

    /**
     * Get all training data parts for a given identifier with their content.
     */
    getSourcesByIdentifier(identifier: string): Observable<SourceTextContent[]> {
        return this.http.get<SourceTextContent[]>(`${environment.apiUrl}${this.baseUrl}/sources/${identifier}`);
    }

    /**
     * Get the image for a source text.
     */
    getSourceImage(textId: number, transliterationId: number): Observable<Blob> {
        return this.http.get(`${environment.apiUrl}/cured/transliterationImage/${textId}/${transliterationId}`, {
            responseType: 'blob'
        });
    }

    /**
     * Upload an image (copy/photo) to a production text.
     */
    uploadImage(productionId: number, file: File, label: string): Observable<UploadedImage> {
        const formData = new FormData();
        formData.append('file', file);
        formData.append('label', label);

        return this.http.post<UploadedImage>(
            `${environment.apiUrl}${this.baseUrl}/text/${productionId}/image`,
            formData
        );
    }

    /**
     * Get an uploaded image from a production text.
     */
    getUploadedImage(productionId: number, imageId: string): Observable<Blob> {
        return this.http.get(
            `${environment.apiUrl}${this.baseUrl}/text/${productionId}/image/${imageId}`,
            { responseType: 'blob' }
        );
    }

    /**
     * Delete an uploaded image from a production text.
     */
    deleteUploadedImage(productionId: number, imageId: string): Observable<{ deleted: boolean }> {
        return this.http.delete<{ deleted: boolean }>(
            `${environment.apiUrl}${this.baseUrl}/text/${productionId}/image/${imageId}`
        );
    }

    /**
     * Mark a production text as exported to eBL.
     */
    markExported(productionId: number): Observable<{ success: boolean; is_exported: boolean }> {
        return this.http.post<{ success: boolean; is_exported: boolean }>(
            `${environment.apiUrl}${this.baseUrl}/text/${productionId}/mark-exported`,
            {}
        );
    }

    /**
     * KWIC concordance search across all transliteration lines.
     */
    searchKwic(query: string, limit: number = 200): Observable<KwicResult[]> {
        return this.http.get<KwicResult[]>(
            `${environment.apiUrl}${this.baseUrl}/search/kwic`,
            { params: { q: query, limit: limit.toString() } }
        );
    }
}

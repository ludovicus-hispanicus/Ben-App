
import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';

import { environment } from 'src/environments/environment';
import { GalleryItem, TextIdentifiers, TextPreview } from '../models/cured';
import { Observable } from 'rxjs';


@Injectable({ providedIn: 'root' })
export class TextService {
    public baseUrl = "/text"
    constructor(private http: HttpClient) { }


    getTextByBenId(benId: number) {
        return this.http.get<string>(`${environment.apiUrl}${this.baseUrl}/${benId}`);
    }

    getTextTransliterations(benId: number) {
        return this.http.get<string>(`${environment.apiUrl}${this.baseUrl}/${benId}/transliterations`);
    }

    isExists(benId: number) {
        return this.http.get<boolean>(`${environment.apiUrl}${this.baseUrl}/isExists/${benId}`);
    }

    getMuseums() {
        return this.http.get<string[]>(`${environment.apiUrl}${this.baseUrl}/museums`);
    }

    list() {
        return this.http.get<TextPreview[]>(`${environment.apiUrl}${this.baseUrl}/list`);
    }


    getTextIdByIdentifiers(textIdentifiers: TextIdentifiers) {
        return this.http.post<number>(`${environment.apiUrl}${this.baseUrl}/textByIdentifiers`, {
            "text_identifiers": textIdentifiers
        });
    }

    create(textIdentifiers: TextIdentifiers, metadata=[], datasetId: number = null) {
        const body: any = {
            "text_identifiers": textIdentifiers,
            "metadata": metadata
        };
        if (datasetId) {
            body.dataset_id = datasetId;
        }
        return this.http.post<number>(`${environment.apiUrl}${this.baseUrl}/create`, body);
    }

    searchBySymbol(symbol: string) {
        return this.http.get<GalleryItem[]>(`${environment.apiUrl}${this.baseUrl}/textBySymbol/${symbol}`);
    }

    getRandomTexts() {
        return this.http.get<GalleryItem[]>(`${environment.apiUrl}${this.baseUrl}/getRandomTexts/`);
    }

    getLabels() {
        return this.http.get<string[]>(`${environment.apiUrl}${this.baseUrl}/labels`);
    }

    getPartsByIdentifier(identifier: string) {
        return this.http.get<number[]>(`${environment.apiUrl}${this.baseUrl}/parts-by-identifier`, {
            params: { identifier }
        });
    }

    updateLabel(textId: number, label: string) {
        return this.http.patch<{updated: boolean}>(`${environment.apiUrl}${this.baseUrl}/${textId}/label`, { label });
    }

    updateLabels(textId: number, labels: string[]) {
        return this.http.patch<{updated: boolean}>(`${environment.apiUrl}${this.baseUrl}/${textId}/labels`, { labels });
    }

    updatePart(textId: number, part: string) {
        return this.http.patch<{updated: boolean}>(`${environment.apiUrl}${this.baseUrl}/${textId}/part`, { part });
    }

    updateIdentifiers(textId: number, museumId: string, pNumber: string, publicationId: string) {
        return this.http.patch<{updated: boolean}>(`${environment.apiUrl}${this.baseUrl}/${textId}/identifiers`, {
            museum_id: museumId || null,
            p_number: pNumber || null,
            publication_id: publicationId || null
        });
    }
}
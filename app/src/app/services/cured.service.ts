
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

    getTransliterations(imageBase64: string) {
        return this.http.post<CuredResult>(`${environment.apiUrl}${this.baseUrl}/getTransliterations`, {"image": imageBase64});
    }

    getTextTransliterations(benId: number) {
        return this.http.get<CuredTransliterationPreview[]>(`${environment.apiUrl}${this.baseUrl}/${benId}/transliterations`);
    }

    loadTransliteration(textId: number, transliterationId: number) {
        return this.http.get<CuredTransliterationData>(`${environment.apiUrl}${this.baseUrl}/transliteration/${textId}/${transliterationId}`);
    }

    saveImage(file: File, textId: number) {
        let url = "/saveImage";
        
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

}
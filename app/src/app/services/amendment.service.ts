import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';

import { environment } from 'src/environments/environment';
import { AmendmentStats, Dimensions, Letter, LetterDto, Prediction, Predictions, SignsData, StageOne } from '../models/letter';
import { Observable } from 'rxjs';
import { CureSettings } from '../components/amendment/amendment.component';
import { GalleryItem } from '../models/cured';


@Injectable({ providedIn: 'root' })
export class AmendmentService {
    public baseUrl = "/amendment"
    public _cachedLabels = null;
    constructor(private http: HttpClient) { }

    getStageOne(settings: CureSettings, oldTextId: string = "", requested_text_id: string = "", file: File=null) {
        let url = "/stageOne";
        const uploadData = new FormData();
        
        if(file) { 
            uploadData.append('file', file, file.name);
            url += "File"
        } else {
            uploadData.append('requested_text_id', requested_text_id);
        }

        if(oldTextId != "") {
            uploadData.append('old_text_id', oldTextId);
        }

        uploadData.append('use_detectron', settings.useDetectron.toString());
        uploadData.append('detectron_sensitivity', settings.detectronSensitivity.toString());
        
        return this.http.post<StageOne>(`${environment.apiUrl}${this.baseUrl}${url}`, uploadData);
    }

    generateBoxes(settings: CureSettings, textID: string = "") {
        let url = "/generateBoxes";
        const uploadData = new FormData();
        
        uploadData.append('text_id', textID);
        uploadData.append('use_detectron', settings.useDetectron.toString());
        uploadData.append('detectron_sensitivity', settings.detectronSensitivity.toString());
        
        return this.http.post<Dimensions[][]>(`${environment.apiUrl}${this.baseUrl}${url}`, uploadData);
    }

    getPredictions(imageName: string, dimensions: Dimensions[][]) {
        return this.http.post<Predictions>(`${environment.apiUrl}${this.baseUrl}/predictions/`, {
            "dimensions": dimensions,
            "text_id": imageName
        });
    }

    getSignsData() {
        return this.http.get<SignsData>(`${environment.apiUrl}${this.baseUrl}/signsData`);
    }

    getSpecificPredictions(imageName: string, dimensions: Dimensions[]) {
        return this.http.post<Prediction[][]>(`${environment.apiUrl}${this.baseUrl}/specificPredictions/`, {
            "dimensions": dimensions,
            "text_id": imageName
            });
    }

    postSubmit(imageName: string, letters: LetterDto[][], akkademiaLines: string[], isFixed: boolean) {
        return this.http.post<AmendmentStats>(`${environment.apiUrl}${this.baseUrl}/submit/`,
         {
            "items": letters,
            "akkademia": akkademiaLines,
            "text_id": imageName,
            "is_fixed": isFixed
        });
    }

    getImage(imageName: string): Observable<Blob> {
        return this.http.get(this.getImageUrl(imageName), { responseType: 'blob' });
    }

    getImageUrl(imageName: string) {
        return `${environment.apiUrl}${this.baseUrl}/image/${imageName}`;
    }

    searchBySymbol(symbol: string) {
        return this.http.get<GalleryItem[]>(`${environment.apiUrl}${this.baseUrl}/textBySymbol/${symbol}`);
    }

    getRandomTexts() {
        return this.http.get<GalleryItem[]>(`${environment.apiUrl}${this.baseUrl}/randomTexts/`);
    }

    setInProgress(textId: string) {
        return this.http.post(`${environment.apiUrl}${this.baseUrl}/set-in-progress/${textId}`, {});
    }
}
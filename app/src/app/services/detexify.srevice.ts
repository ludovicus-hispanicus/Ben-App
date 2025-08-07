import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';

import { environment } from 'src/environments/environment';
import { Prediction } from '../models/letter';



@Injectable({ providedIn: 'root' })
export class DetexifyService {
    public baseUrl = "/detexify"

    constructor(private http: HttpClient) { }

    postSingleImageGuess(imageBase64: string) {
        return this.http.post<Prediction[]>(`${environment.apiUrl}${this.baseUrl}/singleGuess`, {"image": imageBase64});
    }
}
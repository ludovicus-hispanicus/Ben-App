import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';

import { environment } from 'src/environments/environment';

@Injectable({ providedIn: 'root' })
export class AboutService {
    public baseUrl = "/about"

    constructor(private http: HttpClient) { }

    readme() {
        return this.http.get<string>(`${environment.apiUrl}${this.baseUrl}/readme`);

    }
}
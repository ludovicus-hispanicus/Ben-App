import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';

import { environment } from 'src/environments/environment';
import { LoginResult, User } from '../models/letter';



@Injectable({ providedIn: 'root' })
export class UsersService {
    public baseUrl = "/users"

    constructor(private http: HttpClient) { }

    login(email: string, password: string) {
        // //console.log("got ", email, " ", password);
        return this.http.post<LoginResult>(`${environment.apiUrl}${this.baseUrl}/login`, {"email": email, "password": password});
    }

    listAll() {
        return this.http.get<User[]>(`${environment.apiUrl}${this.baseUrl}/list`);

    }

    create(user: User) {
        return this.http.post<string>(`${environment.apiUrl}${this.baseUrl}/create`, user);
    }

    delete(email: string) {
        return this.http.get<string>(`${environment.apiUrl}${this.baseUrl}/delete/${email}`);
    }

    changePermissions(email: string, isAdmin: boolean) {
        return this.http.get<string>(`${environment.apiUrl}${this.baseUrl}/changePermissions/${email}/${isAdmin}`);
    }

    
}
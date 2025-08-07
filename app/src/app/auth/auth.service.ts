import { Injectable } from '@angular/core';
import { JwtHelperService } from '@auth0/angular-jwt';
import { TokenStorageService, TOKEN_KEY } from './token-storage.service';

@Injectable({
  providedIn: 'root'
})
export class AuthService {
  constructor(public jwtHelper: JwtHelperService,
              public tokenService: TokenStorageService) {}
  // ...
  public isAuthenticated(): boolean {
    try {
      const token = localStorage.getItem(TOKEN_KEY);
      if(token) {
        return !this.tokenExpired(token);
      }
    } catch {
      //console.log("error!");
    }
    return false;
  }

  public isAdmin(): boolean {
    return this.isAuthenticated() && this.tokenService.getUser().admin;
  }

  private tokenExpired(token: string) {
    const expiry = (JSON.parse(atob(token.split('.')[1]))).expires;
    return (Math.floor((new Date).getTime() / 1000)) >= expiry;
  }
}
import { Injectable } from '@angular/core';
import { JwtHelperService } from '@auth0/angular-jwt';
import { TokenStorageService, TOKEN_KEY } from './token-storage.service';

@Injectable({
  providedIn: 'root'
})
export class AuthService {
  constructor(public jwtHelper: JwtHelperService,
              public tokenService: TokenStorageService) {}
  // Desktop app - always authenticated
  public isAuthenticated(): boolean {
    return true;
  }

  public isAdmin(): boolean {
    // Desktop app - always admin
    return true;
  }

  private tokenExpired(token: string) {
    const expiry = (JSON.parse(atob(token.split('.')[1]))).expires;
    return (Math.floor((new Date).getTime() / 1000)) >= expiry;
  }
}
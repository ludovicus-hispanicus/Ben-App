import { Component } from '@angular/core';
import { Router } from '@angular/router';
import { AuthService } from './auth/auth.service';
import { TokenStorageService } from './auth/token-storage.service';
import {Title} from "@angular/platform-browser";
import { environment } from 'src/environments/environment';


@Component({
  selector: 'app-root',
  templateUrl: './app.component.html',
  styleUrls: ['./app.component.scss']
})

export class AppComponent {
  title = 'uni-app';
  public isAuthenticated: boolean = false;
  
  constructor(public authService: AuthService,
              public tokenStorageService: TokenStorageService,
              public router: Router, 
              private titleService: Title) {
    this.isAuthenticated = authService.isAuthenticated();
    if(environment.production) {
      this.titleService.setTitle("Babylonian Engine");
    } else {
      this.titleService.setTitle("Babylonian Engine");
    }
  }

  logout() {
    this.isAuthenticated = false;
    this.tokenStorageService.signOut();
    this.router.navigate(['home']);
  }

}


import { Component, OnInit } from '@angular/core';
import { Router } from '@angular/router';
import { TokenStorageService } from 'src/app/auth/token-storage.service';

@Component({
  selector: 'app-home',
  templateUrl: './home.component.html',
  styleUrls: ['./home.component.scss']
})
export class HomeComponent implements OnInit {

  constructor(public tokenStorageService: TokenStorageService,
              private router: Router) { }

  ngOnInit() {
  }

  goToNewProject() {
    this.router.navigate(['amendment']);
  }

  goToDashboard() {
    this.router.navigate(['dashboard']);
  }
}

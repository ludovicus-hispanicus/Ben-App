import { Component, ElementRef, OnInit, ViewChild } from '@angular/core';
import { Router } from '@angular/router';
import { AuthService } from 'src/app/auth/auth.service';
import { TokenStorageService } from 'src/app/auth/token-storage.service';
import { NotificationService } from 'src/app/services/notification.service';
import { UsersService } from 'src/app/services/user.service';

@Component({
  selector: 'app-home',
  templateUrl: './home.component.html',
  styleUrls: ['./home.component.scss']
})
export class HomeComponent implements OnInit {

  constructor(private usersService: UsersService,
              public tokenStorageService: TokenStorageService,
              private notifService: NotificationService,
              public authService: AuthService,
              private router: Router) { }

  @ViewChild("username") username: ElementRef;
  @ViewChild("password") password: ElementRef;

  ngOnInit() {
  }

  goToGallery() {
    this.router.navigate(['gallery']);
  }

  login() {
    this.usersService.login(this.username.nativeElement.value, this.password.nativeElement.value).subscribe(data =>{
        this.tokenStorageService.saveToken(data.token);
        this.tokenStorageService.saveUser(data.user);
        // this.router.navigate(['amendment']);
      }, error => {
        //console.log("error , ", error);
    });
  


  }
}




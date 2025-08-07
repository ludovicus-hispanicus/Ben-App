import { LEADING_TRIVIA_CHARS } from '@angular/compiler/src/render3/view/template';
import { ChangeDetectorRef, Component, OnInit, ViewChild } from '@angular/core';
import { MatDialog } from '@angular/material/dialog';
import { MatTable } from '@angular/material/table';
import { Router } from '@angular/router';
import { AuthService } from 'src/app/auth/auth.service';
import { TokenStorageService } from 'src/app/auth/token-storage.service';
import { TextPreview } from 'src/app/models/cured';
import { User } from 'src/app/models/letter';
import { NotificationService } from 'src/app/services/notification.service';
import { TextService } from 'src/app/services/text.service';
import { UsersService } from 'src/app/services/user.service';
import { TextCreatorComponent } from '../common/text-creator/text-creator.component';




@Component({
  selector: 'app-admin-panel',
  templateUrl: './admin-panel.component.html',
  styleUrls: ['./admin-panel.component.scss']
})
export class AdminPanelComponent implements OnInit {

  constructor(public usersService: UsersService, public notificationService: NotificationService,
              public textService: TextService, private changeDetectorRefs: ChangeDetectorRef,
               private tokenService: TokenStorageService,
               public dialog: MatDialog,
               public router: Router) { }

  public displayedColumns: string[] = ['delete', 'name', 'email', 'admin', 'change_permissions'];
  public users: User[] = []

  public curedDisplayedColumns: string[] = ['last_modified', 'text_id', 'p_number', 'museum', 'transliterations', 'uploader_id'];
  public curedTexts: TextPreview[] = []

  public newUser: User = new User();
  public newUserPassword: string = null;
  public newUserEmail: string = null;


  @ViewChild('table', {static: false}) table : MatTable<User>


  ngOnInit(): void {
    this.usersService.listAll().subscribe(data => {
      this.users = data;
    })

    this.textService.list().subscribe(data => {
      this.curedTexts = data;
    })
  }

  resetCreate() {
    this.newUserPassword = null;
    this.newUser = new User();
  }

  showTransliterations(element) {
    this.openDialog(element.text_id)
  }

  openDialog(textId) {
    const dialogRef = this.dialog.open(TextCreatorComponent);
    dialogRef.componentInstance.selectTransliteration = true;
    dialogRef.componentInstance.showFindText = false;
    dialogRef.componentInstance.textId = textId;
    dialogRef.componentInstance.loadTransliterations();
    // dialogRef.componentInstance.showFindText = true;

    dialogRef.afterClosed().subscribe(result => {
      if(result) {
        let textId = result[0];
        let transliterationId = result[1];
        this.router.navigate(['/cured'], {
          queryParams: {
            textId: textId,
            transId: transliterationId 
          },
        });
      }
    });
  }

  getPOfElement(element) {
    if(element.text_identifiers.p_number) {
      return `P-${element.text_identifiers.p_number.number}`
    } else {
      return ""
    }
  }

  getMuseumOfElement(element) {
    if(element.text_identifiers.museum) {
      let short = element.text_identifiers.museum.name.substring(0, 4)
      return `${short}...${element.text_identifiers.museum.number}`
    } else {
      return ""
    }
  }

  getHoverValueMuseum(element) {
    if(element.text_identifiers.museum) {
      return `${element.text_identifiers.museum.name}-${element.text_identifiers.museum.number}`
    } else {
      return ""
    }
  }

  changePermissions(user: User) {
    if(user.email == this.tokenService.getUser().email) {
      alert("I can't believe you tried this. Don't revoke yourself!")
      return;
    }

    if(user.admin) {
      if(!confirm(`Are you sure you want to revoke ${user.email}'s admin?`)) {
        return;
      }
    } else {
      if(!confirm(`Are you sure you want to make ${user.email} an admin?`)) {
        return;
      }
    }

    this.usersService.changePermissions(user.email, !user.admin).subscribe(data => {
      this.notificationService.showInfo(`Permissions changed`);
      user.admin = !user.admin;
      this.table.renderRows();
    })
  }

  deleteUser(userToDelete: User) {
    if(userToDelete.email == this.tokenService.getUser().email) {
      alert("I can't believe you tried this. Don't delete yourself!")
      return;
    }


    if(!confirm(`Are you sure you want to delete ${userToDelete.email}?`)) {
      return;
    }

    this.usersService.delete(userToDelete.email).subscribe(data => {
      this.notificationService.showSuccess(`User ${userToDelete.email} deleted`);
      this.users = this.users.filter(user => user.email != userToDelete.email);
      this.table.renderRows();

    })
  }

  createUser() {
    let regexp = new RegExp(/^(([^<>()\[\]\\.,;:\s@"]+(\.[^<>()\[\]\\.,;:\s@"]+)*)|(".+"))@((\[[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}])|(([a-zA-Z\-0-9]+\.)+[a-zA-Z]{2,}))$/);
    let isValidEmail = regexp.test(this.newUser.email);

    let isValidName = this.newUser.name.length >= 4;

    if(!isValidEmail || !isValidName) {
      alert("Invalid email or fullname");
      return;
    }

    if(this.newUser.admin) {
      if(!confirm(`Are you sure you want add ${this.newUser.email} as an ADMIN?`)) {
        return;
      }
    } else {
      if(!confirm(`Are you sure you want add ${this.newUser.email}?`)) {
        return;
      }
    }

    this.usersService.create(this.newUser).subscribe(data => {
      this.notificationService.showInfo(`${this.newUser.email} added`);
      this.newUserPassword = data;
      this.newUserEmail = this.newUser.email;
      this.users.push(this.newUser);
      this.table.renderRows();
    })
  }

}

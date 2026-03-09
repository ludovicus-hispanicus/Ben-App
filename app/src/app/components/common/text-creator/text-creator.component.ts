import { Component, Inject, Input, OnInit, ViewChild } from '@angular/core';
import { MatDialogRef } from '@angular/material/dialog';
import { MatStepper } from '@angular/material/stepper';
import { CuredTransliterationPreview } from 'src/app/models/cured';
import { CuredService } from 'src/app/services/cured.service';
import { NotificationService } from 'src/app/services/notification.service';
import { TextService } from 'src/app/services/text.service';

import {MatDialog, MAT_DIALOG_DATA} from '@angular/material/dialog';

@Component({
  selector: 'text-creator',
  templateUrl: './text-creator.component.html',
  styleUrls: ['./text-creator.component.scss']
})
export class TextCreatorComponent implements OnInit {

  @Input()  public textId: number;

  @ViewChild('stepper') private myStepper: MatStepper;
  @Input() public selectTransliteration: boolean = false;
  @Input() public showCreateOnNoResult: boolean = true;
  @Input() public showFindText: boolean = true;

  public displayedColumns: string[] = ['select', 'uploader_id', 'last_edited', 'image_name'];
  public transliterations: CuredTransliterationPreview[] = null;
  
  constructor(private textService: TextService,
              private curedService: CuredService,
              private notificationService: NotificationService,
              public matDialogRef: MatDialogRef<TextCreatorComponent>,
              public dialog: MatDialog) { }

  ngOnInit(): void {
  }

  submit() {
    this.matDialogRef.close(this.textId);
  }


  selectedText(textId: number) {
    if(!this.selectTransliteration) {
      this.matDialogRef.close(textId);
    } else {
      this.textId = textId;
      this.myStepper.next();
      this.loadTransliterations();
    }
    // this.benNumber = textId;
  }

  loadTransliterations() {
    this.curedService.getTextTransliterations(this.textId).subscribe(data =>
      {
        this.transliterations = data;
      }
    );
  }

  transliterationSelected(row) {
    console.log(row);
    this.notificationService.showInfo(row.transliteration_id);
    this.matDialogRef.close([this.textId, row.transliteration_id]);
  }

  showImage(row) {
    let imageToShow: any;
    let reader = new FileReader();
    reader.addEventListener("load", () => {
      imageToShow = reader.result;   
      console.log(imageToShow)
      this.dialog.open(ImageDialog, {
        data: {
          image: imageToShow,
        },
      });

    }, false);
    console.log(row);
    this.curedService.getImage(this.textId, row.transliteration_id).subscribe(data => {
      reader.readAsDataURL(data);   
    })
  }

  

}

export interface DialogData {
  image: any;
}

@Component({
  selector: 'image-dialog',
  templateUrl: 'image-dialog.html',
})
export class ImageDialog {
  constructor(@Inject(MAT_DIALOG_DATA) public data: DialogData) {}
}

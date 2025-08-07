import { Component, OnInit } from '@angular/core';
import { MatDialog } from '@angular/material/dialog';
import { Router } from '@angular/router';
import { AmendmentService } from 'src/app/services/amendment.service';
import { CuredService } from 'src/app/services/cured.service';
import { NotificationService } from 'src/app/services/notification.service';
import { TextService } from 'src/app/services/text.service';
import { ImageDialog } from '../common/text-creator/text-creator.component';

@Component({
  selector: 'app-gallery',
  templateUrl: './gallery.component.html',
  styleUrls: ['./gallery.component.scss']
})
export class GalleryComponent implements OnInit {


  // images is object that contains url title and description
  images = [];

  public signs = [];
  public unicodeToSigns = {};
  public searchText: string
  public source: string
  public date: string
  public author: string
  public university : string

  public symbol: string
  public unicodeQuery: string
  public searchTypes = ["transliteration", "unicode"];
  public searchType: string = this.searchTypes[0];

  
  // public images = [];

  constructor(private amendmentService: AmendmentService,
              private curedService: CuredService,
              private notifyService : NotificationService,
              private textService: TextService,
              public dialog: MatDialog,
              private router: Router) {
    this.loadSymbols();
    }

  ngOnInit(): void {
    this.textService.getRandomTexts().subscribe(data => {
      this.processCuredSearchResult(data);
    });
    this.amendmentService.getRandomTexts().subscribe(data => {
      this.processAmendmentSearchResult(data);
    });
    // shuffle the images
    this.images.sort(() => Math.random() - 0.5);
  }

  searchTypeChanged() {
    this.images = [];
  }

  getUnicodeQuery() {
    return "for: " + this.unicodeQuery;
  }

  symbolSelectionChanged(event) {
    this.unicodeQuery = event.label;
    this.amendmentService.searchBySymbol(event.label).subscribe(data => {
      this.processAmendmentSearchResult(data);
    })
  }

  processAmendmentSearchResult(data) {
    if(data.length == 0) {
      this.notifyService.showInfo("No results...")
    }
    this.images = [];
    data.forEach(item => {
      this.images.push({
        url: `data:image/jpeg;base64,${item.image_base64}`,
        title: `Uploaded by: ${item.uploader_id}`,
        description: `Text: ${item.text_id}`,
        textId: item.text_id,
        transliterationId: item.transliteration_id
      });
    });
  }
  
  search() {
    // validate length
    if (this.symbol.length < 1) {
      return;
    }

    this.textService.searchBySymbol(this.symbol).subscribe(data => {
      this.processCuredSearchResult(data);
    })
  }

  processCuredSearchResult(data) {
    if(data.length == 0) {
      this.notifyService.showInfo("No results...")
    }
    this.images = [];
    data.forEach(item => {
      this.images.push({
        url: `data:image/jpeg;base64,${item.image_base64}`,
        title: `Uploaded by: ${item.uploader_id}`,
        description: `Text: ${item.text_id}`,
        textId: item.text_id,
        transliterationId: item.transliteration_id
      });
    });
  }

  clear() {
    this.symbol = '';
    this.images = [];
  }

  goToCure(textId) {
    // http://localhost:4200/cured?textId=1&transId=1 redierct to this url
    this.router.navigate(['/amendment'], {
      queryParams: {
        textId: textId, 
        query: this.unicodeQuery,
      },
    });
  }

  goToCured(textId, transliterationID) {
    // http://localhost:4200/cured?textId=1&transId=1 redierct to this url
    this.router.navigate([`/cured`], {
      queryParams: {
        textId: textId, 
        transId: transliterationID,
        viewOnly: true,
        query: this.symbol
      },
    });
  }

  showImage(textId, transliterationID) {
    let imageToShow: any;
    let reader = new FileReader();
    reader.addEventListener("load", () => {
      imageToShow = reader.result;   
      this.dialog.open(ImageDialog, {
        data: {
          image: imageToShow,
        },
      });

    }, false);

    if(textId == transliterationID) { // cure
      this.amendmentService.getImage(textId).subscribe(data => {
        reader.readAsDataURL(data);   
      })
    } else {
      this.curedService.getImage(textId, transliterationID).subscribe(data => {
        reader.readAsDataURL(data);   
      })
    }
  }

  loadSymbols() {
    let labelToUnicode = [];
    this.amendmentService.getSignsData().subscribe(data => {
      let dict = data.label_to_unicode;
      Object.keys(dict).forEach(key => {
        labelToUnicode.push({letter: key, symbol: dict[key]})
        this.signs = labelToUnicode;
      });
      this.signs.sort(function(a, b) {
        return a.letter.localeCompare(b.letter);
      });

      this.unicodeToSigns = data.unicode_to_labels;
    });
  }



}

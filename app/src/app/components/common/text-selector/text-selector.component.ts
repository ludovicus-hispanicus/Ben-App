import { Component, OnInit, Output, EventEmitter, Input } from '@angular/core';
import { MatDialogRef } from '@angular/material/dialog';
import { TextIdentifier, TextIdentifiers } from 'src/app/models/cured';
import { CuredService } from 'src/app/services/cured.service';
import { NotificationService } from 'src/app/services/notification.service';
import { TextService } from 'src/app/services/text.service';
import { SelectorState } from '../smart-selector/smart-selector.component';



export enum IdentifierType {
  CDLI = "CDLI No.",
  Publication = "Publication",
  Museum = "Museum Item",
  BEn = "BEn No."
}

@Component({
  selector: 'text-selector',
  templateUrl: './text-selector.component.html',
  styleUrls: ['./text-selector.component.scss']
})
export class TextSelectorComponent implements OnInit {

  constructor(private textService: TextService,
              private notificationService: NotificationService,
              public matDialogRef: MatDialogRef<TextSelectorComponent>) {

  }

  public museums: SelectorState[] = []; 
  public publications: SelectorState[] = [{value: "gordins publications"},{value: "avital pubs"}]; 


  public benNumber: number;

  public completedSearch: boolean = false;


  public searchGotNoResult = false;
  @Input() public showCreateOnNoResult: boolean = true;
  @Input() public isDialog: boolean = true;


  public textIdentifiers: TextIdentifiers = new TextIdentifiers();

  
  @Output() selectedTextId: EventEmitter<number> = new EventEmitter();


  ngOnInit(): void {
    this.loadMuseums();
  }

  loadMuseums() {
    if(this.museums.length != 0) {
      return;
    }
    
    let museums = [];
    this.textService.getMuseums().subscribe(data => {
      data.forEach(museum => {
        museums.push({value: museum})
      });
      museums.sort(function(a, b) {
        return a.value.localeCompare(b.value);
      });
      this.museums = museums;
      console.log(this.museums);
    });
  }

  searchByBen() {
    this.textService.isExists(this.benNumber).subscribe(isExist => {
      if(isExist) {
        this.emitTextId(this.benNumber);
      } else {
        this.searchTextFailed();
      }
    });
  }
  
  searchByIdentifiers() {
    this.textService.getTextIdByIdentifiers(this.createTextIdentifiersQuery()).subscribe(textId => {
      if(textId != -1) {
        this.emitTextId(textId);
      } else {
        this.searchGotNoResult = true;
        this.searchTextFailed();
      }
    })
  }
     
  searchTextFailed() {
    this.notificationService.showWarning(`text doesn't exist`)
  }

  emitTextId(textId) {
    this.selectedTextId.emit(textId);
    this.notificationService.showSuccess(`Success! text id - ${textId}`);
    if(this.isDialog) {
      this.matDialogRef.close();
    }
  }

  create() {
    this.textService.create(this.createTextIdentifiersQuery()).subscribe(textId => {
      this.emitTextId(textId);
    })
  }

  createTextIdentifiersQuery(): TextIdentifiers {
    let query = new TextIdentifiers();

    if(this.isMusemValid()) {
      query.museum = this.textIdentifiers.museum;
    } else{
      delete query.museum;
    }

    if(this.isPublicationValid()) {
      query.publication = this.textIdentifiers.publication;
    } else {
      delete query.publication;
    }

    if(this.textIdentifiers.p_number.number != null) {
      query.p_number = new TextIdentifier("p", this.textIdentifiers.p_number.number)
    } else {
      delete query.p_number;
    }

    console.log(query);
    return query;
  }

  isPublicationValid() {
    return this.isValidSelectableField(this.textIdentifiers.publication.name, this.publications) && this.textIdentifiers.publication != null;
  }

  isMusemValid() {
    return this.isValidSelectableField(this.textIdentifiers.museum.name, this.museums) && this.textIdentifiers.museum.number != null;
  }

  canSearchByIdentifiers() {
     return this.isPublicationValid() || this.isMusemValid() || this.textIdentifiers.p_number.number != null;
  }

  isValidSelectableField(state: string, options: SelectorState[]) {
    return state != null && this.isValidString(state) && options.some(a => a.value == state);
  }

  isValidString(str) {
    return str != null && str.length > 0;
  }

}

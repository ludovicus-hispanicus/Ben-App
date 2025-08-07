import { Component, EventEmitter, Input, OnInit, Output, ViewChild } from '@angular/core';
import { FormControl } from '@angular/forms';
import { Letter, LetterView } from 'src/app/models/letter';
import {Observable} from 'rxjs';
import { SmartSelectorComponent } from '../../common/smart-selector/smart-selector.component';

export interface SignData {
  letter: string,
  symbol: string
}


export interface UnicodeData {
  symbol: string
  signs: string[],
}




@Component({
  selector: 'letter-viewer',
  templateUrl: './letter-viewer.component.html',
  styleUrls: ['./letter-viewer.component.scss']
})
export class LetterViewerComponent implements OnInit {

  public prediction: Letter;
  public transliteration: Letter;
  public letterView: LetterView;

  @ViewChild('signSelector') signSelector: SmartSelectorComponent;


  public _isEdit: boolean = false;
  @Input() public signs: SignData[]  = []
  
  stateCtrl = new FormControl();

  @Input() public isEditMode: boolean = false;


  public filteredStates: Observable<SignData[]>;

  constructor() {
  }


  ngOnInit(): void {
  }

  public setLetters( letterView: LetterView, transliteration?: Letter) {
    this.letterView = letterView;
    this.transliteration = transliteration;
  }


}

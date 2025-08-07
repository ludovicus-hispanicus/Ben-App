import { Component, Input, OnInit, Output, EventEmitter } from '@angular/core';
import { Letter, LetterHover } from 'src/app/models/letter';

@Component({
  selector: 'app-letter',
  templateUrl: './letter.component.html',
  styleUrls: ['./letter.component.scss']
})
export class LetterComponent implements OnInit {

  constructor() { }

  @Input() public LetterModel: Letter;
  @Input() public showSign: boolean = true;
  @Input() public showSymbol: boolean = true;
  @Input() public pointerCursor: boolean = false;
  @Input() public showCustomFont: boolean = true;
  @Input() public probability: number = null;
  @Input() public editMode: boolean = false;

  @Output() toggle: EventEmitter<LetterHover> = new EventEmitter<LetterHover>();
  @Output() letterClick: EventEmitter<any> = new EventEmitter();
  @Output() lineFocus: EventEmitter<any> = new EventEmitter();
  
  public bckgColor: string = "transparent";  

  ngOnInit(): void {
  }

  getScore() {
    return (this.probability * 100).toString().slice(0, 5) + "%";
  }

  onNameChange(event) {
    this.LetterModel.letter = event.target.innerHTML;
  }

  getWidth() {
    if(this.editMode) {
      return "100%";
    } else {
      return "";
    }
  }

  getLetterView() {
    let view = this.LetterModel.letter;
    if(view == "") {
      return "NONE";
    }

    if(this.LetterModel.certainty) {
      view += this.LetterModel.certainty;
    }
    return view;
    
  }

  highlight() {
    this.LetterModel.selected = true;
  }

  unhighlight() {
    this.LetterModel.selected = false;
  }

  enter(event) {
    // this.highlight();
    this.toggle.emit(new LetterHover(this.LetterModel.index, true, event));
  }

  leave(event) {
    // this.unhighlight();
    this.toggle.emit(new LetterHover(this.LetterModel.index, false, event));
  }

  onClick() {
    if(this.pointerCursor) {
      this.letterClick.emit();
    }
  }

  getBorder() {
    return 'none';
  }

  getBackgroundColor() {
    if(!this.LetterModel) { return 'null'}

    if(this.LetterModel.highlight) {
      return 'rgba(255,255,0,0.3)';
    }
    else if(this.LetterModel.selected) {
      return 'rgba(0,0,255,0.1)';
    }
    else if(this.LetterModel.letter == "" || this.LetterModel.wrong) {
      return 'rgba(255,0,0,0.1)';
    }
    else if(this.LetterModel.right) {
      return 'rgba(0,255,0,0.1)';
    }
    else {
      return 'transparent';
    }
  }

  getCursor() {
    if(this.pointerCursor || this.showSymbol) {
      return 'pointer';
    } else {
      return 'auto';
    }
  }

  getFont() {
    if(this.showSymbol && this.showCustomFont) {
      return 'Esagil'
    } else {
      return "Arial"
    }
  }

  getFontSize() {
    if(this.showSymbol) {
      return "1.5em"
    } else {
      return "1em"
    }
  }

}

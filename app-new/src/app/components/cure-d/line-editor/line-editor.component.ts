import { CdkDragDrop } from '@angular/cdk/drag-drop';
import {  AfterViewInit, Component, EventEmitter, Input, OnInit, Output } from '@angular/core';
import { Index, Letter, LetterHover } from 'src/app/models/letter';
import { NotificationService } from 'src/app/services/notification.service';
import { ShortcutInput } from "ng-keyboard-shortcuts";  

@Component({
  selector: 'line-editor',
  templateUrl: './line-editor.component.html',
  styleUrls: ['./line-editor.component.scss']
})
export class LineEditorComponent implements OnInit, AfterViewInit {

  @Input() public title: string = "CureD lines";

  @Input() public canEdit: boolean = true;

  @Input() public boxAmount: number = null;


  @Output() lineHover: EventEmitter<LetterHover> = new EventEmitter();
  @Output() lineChanged: EventEmitter<number> = new EventEmitter();
  @Output() lineDeleted: EventEmitter<number> = new EventEmitter();


  // @Output() repredictSignEmitter: EventEmitter<Letter> = new EventEmitter<Letter>();
  // @Output() getSignPrediction: EventEmitter<Letter> = new EventEmitter<Letter>();

  public letters: Letter[][];
  public predictions: Letter[][];
  @Input() public isLoadingPredictions: boolean = false;

  public showSignPickers: boolean[] = [];
  public showCustomFont: boolean = true;

  public activeSignEditorLineIndex: number = -1;
  public activeEditSign: Letter = null;

  public isEditMode: boolean = false;
  public showAddLines: boolean = false;


  public selectedLine: Letter = null;

  public focusLine: number = -1;

  @Input() public lines: Letter[] = null;

  console = console;

  public color:string = 'red';

  constructor(private notifyService : NotificationService) {}

  shortcuts: ShortcutInput[] = [];  


  ngOnInit(): void {
  }

  ngAfterViewInit(): void {
    this.shortcuts.push(  
      {  
          key: "alt + w",  
          preventDefault: true,  
          allowIn: ["TEXTAREA" as any, "INPUT" as any], 
          command: e => this.wrap(this.focusLine) 
      },
      {  
        key: "alt + u",  
        preventDefault: true,  
        allowIn: ["TEXTAREA" as any, "INPUT" as any], 
        command: e => this.capitlize(this.focusLine) 
      },
      {  
        key: "alt + l",  
        preventDefault: true,  
        allowIn: ["TEXTAREA" as any, "INPUT" as any], 
        command: e => this.lower(this.focusLine) 
      } 
    );
  }

  lineDrop(event: CdkDragDrop<Task[]>) {
    if (event.previousContainer === event.container) {
      this.moveLine(event.previousIndex, event.currentIndex);
    } else {
    }
  }


  moveLine(lineIndex, toIndex) {
    var fromElement = this.lines[lineIndex];
    this.lines.splice(lineIndex, 1);
    this.lines.splice(toIndex, 0, fromElement);
    // TODO: basically its possible that every line has changed (they all could be shifted by one then all letter index are wrong).
    this.lineChanged.emit(lineIndex);
  }

  deleteLine(lineIndex: number, validate: boolean = true) {
    if(validate) {
      if(!confirm("Are you sure you want to delete this line?")) {
        return;
      }
    }
    
    if (lineIndex != -1) {
      this.lines.splice(lineIndex, 1);
      this.lineChanged.emit(lineIndex);
      this.lineDeleted.emit(lineIndex);
    }
    this.notifyService.showWarning("A line just got deleted")
  }

  addLine(lineIndex) {
    this.lines.splice(lineIndex + 1, 0, new Letter("Empty"));
    this.lineChanged.emit(lineIndex);
  }

  capitlize(lineIndex) {
    if (window.getSelection()) {
      let sel = window.getSelection();
      let text = sel.toString();
      try{
        if(text.length > 0 && this.lines[lineIndex].letter.includes(text)) {
          this.lines[lineIndex].letter = this.lines[lineIndex].letter.replace(text, text.toUpperCase());
        }
      } catch(e) {}
    }
  }

  lower(lineIndex) {
    if (window.getSelection()) {
      let sel = window.getSelection();
      let text = sel.toString();
      try{
        if(text.length > 0 && this.lines[lineIndex].letter.includes(text)) {
          this.lines[lineIndex].letter = this.lines[lineIndex].letter.replace(text, text.toLowerCase());
        }
      } catch(e){}
    }
  }

  wrap(lineIndex) {
    if (window.getSelection()) {
      let sel = window.getSelection();
      let text = sel.toString();
      
      let newText = text;

      if(text.startsWith("{") && text.endsWith("}")) {
        newText = newText.replace("{", "");
        newText = newText.replace("}", "");
      }
      else {
        if(!text.startsWith("{")) {
          newText = `{${newText}`;
        };
  
        if(!text.endsWith("}")) {
          newText = `${newText}}`;
        };
      }

      try{
        if(text.length > 0 && this.lines[lineIndex].letter.includes(text)) {
          this.lines[lineIndex].letter = this.lines[lineIndex].letter.replace(text, newText);
        }
      } catch(e) { console.log(e)}
    }
  }


  setLines(lines: Letter[]) {
    this.lines = lines;
  }


  getCancelButtonIndex() {
    let indexes = [this.activeSignEditorLineIndex,]
    return indexes.find(index => index != -1);
  }

  getWidth() {
    if(this.isEditMode) {
      return "80%;"
    } 
    return "";
  }
  
  cancel() {
    this.resetLineEditActions();
  }

  resetLineEditActions() {
    if(this.activeEditSign) this.activeEditSign.highlight = false;
    this.activeSignEditorLineIndex = -1;
    this.activeEditSign = null;
    this.showAddLines = false;
  }

  startEditing() {
    this.isEditMode = true;
  }

  setEditSignMode(lineIndex) {
    this.resetLineEditActions();
    this.activeSignEditorLineIndex = lineIndex;
  }

  stopEditing() {
    this.resetLineEditActions();
    this.isEditMode = false;
  }

  setLetters(lines: Letter[]) {
    this.lines = lines;
  }


  onLineToggle(event, index) {
    if(event.event.buttons != 0) return;
    this.lineHover.emit(event);
  }

  onLineFocus(event, index) {
    this.focusLine = index;
  }
  

  getBadLineMessage() {
    if(this.boxAmount == null) {
      return "no bounding boxes"
    }

    if(this.boxAmount > this.lines.length) {
      return `${this.boxAmount} boxes and only ${this.lines.length} lines`;
    } else if(this.boxAmount < this.lines.length) {
      return `${this.lines.length} lines and only ${this.boxAmount} boxes`;
    }

    return null;
  }

  //   if(badLine.emptyLetters > 0) {
  //     if(badLine.emptyLetters == 1) {
  //       message += `\nThere is an empty sign.`;
  //     } else {
  //       message += `\nThere are ${badLine.emptyLetters} empty signs.`;
  //     }
  //   }

  //   return message;
  // }

  setNewSelectedLine(index: Index) {
    let newLine = null;

    // unselect old letter if it exists
    if(this.selectedLine) { 
      this.selectedLine.selected = false;
    }

    if(index != null && index.row >= 0 && this.lines.length > index.row) {
      // select new line
      newLine = this.lines[index.row];
      newLine.selected = true;
      this.selectedLine = newLine;
    }
  }

  getBorder(lineIndex) {
    return 'none';
  }

  getBackgroundColor(lineIndex) {
    return 'transparent';
  }

  hardReset() {
    this.letters = []
    this.predictions = null;
  }


}

import { CdkDragDrop } from '@angular/cdk/drag-drop';
import {  Component, EventEmitter, Input, OnInit, Output } from '@angular/core';
import { FormControl, FormGroup, Validators } from '@angular/forms';
import { ShortcutInput } from 'ng-keyboard-shortcuts';
import { Index, Letter, LetterHover, LineError } from 'src/app/models/letter';
import { NotificationService } from 'src/app/services/notification.service';
import { SelectorState } from '../../common/smart-selector/smart-selector.component';
import { SignData } from '../letter-viewer/letter-viewer.component';

@Component({
  selector: 'text-viewer',
  templateUrl: './text-viewer.component.html',
  styleUrls: ['./text-viewer.component.scss']
})
export class TextViewerComponent implements OnInit {

  @Input() public title: string = "title";
  @Input() public isTransliterationViewer: boolean = false;
  @Input() public badLines: LineError[] = [];
  @Input() public showSymbols: boolean = true;
  @Input() public showLetters: boolean = true;

  @Input() public canEdit: boolean = true;

  @Input() public isLoadingPredictions: boolean = false;


  @Input() public showAkkademiaIcon: boolean = false;

  @Input() public signs: SignData[]  = []
  @Input() public unicodesToSigns: Map<string, string[]> = null;


  @Output() letterHover: EventEmitter<LetterHover> = new EventEmitter();
  @Output() letterClick: EventEmitter<Index> = new EventEmitter();
  @Output() lineChanged: EventEmitter<number> = new EventEmitter();
  @Output() repredictSignEmitter: EventEmitter<Letter> = new EventEmitter<Letter>();
  @Output() getSignPrediction: EventEmitter<Letter> = new EventEmitter<Letter>();

  public letters: Letter[][];
  public predictions: Letter[][];
  
  public showSignPickers: boolean[] = [];
  public showCustomFont: boolean = true;

  public activeAddSignPickerLineIndex: number = -1;
  public activeSignEditorLineIndex: number = -1;
  public activeSignDeleteLineIndex: number = -1;
  public activeSignMarkLineIndex: number = -1;
  public activeRepredictSignLineIndex: number = -1;


  public activeEditSign: Letter = null;

  public isEditMode: boolean = false;
  public showAddLines: boolean = false;
  public dragLinesEnabled: boolean = false;

  public showAddCustomSign: boolean = false;
  public lettersArePredictions: boolean = false;

  public selectedLetter: Letter = null;
  public selectedPrediction: Letter = null;

  public editPickerInitialSelection: SignData = null;


  public topLines: string[];
  console = console;

  public color:string = 'red';
  public certaintyOptions = [
                        {"certainty": "!", "description": "unattested/reconstructed sign form"},
                        {"certainty": "?", "description": "uncertain reading"},  
                        {"certainty": "#", "description": "damaged sign"},
                        {"certainty": "#?", "description": "damaged sign, uncertain"}]

  group = new FormGroup({
    cSignControl: new FormControl('', [Validators.required]),
    cUnicodeControl: new FormControl('', [Validators.required])
  })

  shortcuts: ShortcutInput[] = [];  


  constructor(private notifyService : NotificationService) {}

  ngOnInit(): void {
    this.shortcuts.push(  
      // {  
      //     key: "alt + w",  
      //     preventDefault: true,  
      //     allowIn: ["TEXTAREA" as any, "INPUT" as any], 
      //     command: e => this.wrap(this.focusLine) 
      // },
      // {  
      //   key: "alt + u",  
      //   preventDefault: true,  
      //   allowIn: ["TEXTAREA" as any, "INPUT" as any], 
      //   command: e => this.capitlize(this.focusLine) 
      // },
      // {  
      //   key: "alt + l",  
      //   preventDefault: true,  
      //   allowIn: ["TEXTAREA" as any, "INPUT" as any], 
      //   command: e => this.lower(this.focusLine) 
      // } 
    );
  }


  signDrop(event: CdkDragDrop<Task[]>, lineIndex: number) {
    if (event.previousContainer === event.container) {
      // moveItemInArray(event.container.data, event.previousIndex, event.currentIndex);
      // //console.log(lineIndex, event);
      this.moveLetter(lineIndex, event.previousIndex, event.currentIndex);
    } else {
    }
  }

  moveLetter(lineIndex, fromIndex, toIndex) {
    var fromElement = this.letters[lineIndex][fromIndex];

    this.letters[lineIndex].splice(fromIndex, 1);
    this.letters[lineIndex].splice(toIndex, 0, fromElement);

    this.lineChanged.emit(lineIndex);
  }

  lineDrop(event: CdkDragDrop<Task[]>) {
    if (event.previousContainer === event.container) {
      this.moveLine(event.previousIndex, event.currentIndex);
    } else {
    }
  }
  
  moveLine(lineIndex, toIndex) {
    var fromElement = this.letters[lineIndex];
    this.letters.splice(lineIndex, 1);
    this.letters.splice(toIndex, 0, fromElement);
    if(this.topLines != null && this.topLines.length > 0) {
      var fromElement2 = this.topLines[lineIndex];
      this.topLines.splice(lineIndex, 1);
      this.topLines.splice(toIndex, 0, fromElement2);
    }
    // TODO: basically its possible that every line has changed (they all could be shifted by one then all letter index are wrong).
    this.lineChanged.emit(lineIndex);
  }

  removeLetter(letterIndex: Index) {
    if (letterIndex != null) {
      this.letters[letterIndex.row].splice(letterIndex.col, 1);
      this.lineChanged.emit(letterIndex.row);
    }
  }

  deleteLine(lineIndex: number) {
    if(!confirm("Are you sure you want to delete this line?")) {
      return;
    }

    if (lineIndex != -1) {
      if(this.topLines != null && this.topLines.length > 0) {
        this.topLines.splice(lineIndex, 1);
      }
      this.letters.splice(lineIndex, 1);
      this.lineChanged.emit(lineIndex);
    }
    this.notifyService.showWarning("A line just got deleted")
  }

  addLine(lineIndex) {
    // this.letters.unshift([]);
    this.letters.splice(lineIndex + 1, 0, []);
    if(this.topLines != null && this.topLines.length > 0) {
      this.topLines.splice(lineIndex + 1, 0, "");
    }
    this.lineChanged.emit(lineIndex);
  }

  signMarkChanged(evnet) {
    this.activeEditSign = null;
  }

  clearMark() {
    delete this.activeEditSign.certainty
  }


  addPickerSelectionChanged(state: SelectorState, lineIndex: number) {
    if(state == null) {
      this.addSignToLine(lineIndex, "", "");
    } else {
      this.addSignToLine(lineIndex, state.value, state.label);
    }
      
  }

  addSignToLine(lineIndex: number, letter: string, symbol: string) {
    let newLetter = new Letter(letter, symbol);
    this.letters[lineIndex].push(newLetter);
    this.activeAddSignPickerLineIndex = -1;
    this.lineChanged.emit(lineIndex);
  }

  addCustomSign(lineIndex) {
    let sign = this.group.get('cSignControl').value;
    let unicode = this.group.get('cUnicodeControl').value;
    if(!confirm(`Are you sure you want to add ${sign}-${unicode}? this will add it to the system classes`)) {
      return;
    }

    let newLetter = new Letter(sign, unicode);
    this.signs.push(newLetter)

    this.addSignToLine(lineIndex, sign, unicode);
    this.showAddCustomSign = false;
    this.notifyService.showInfo(`${sign}-${unicode} added to the database`)
  }

  initialEditPickerSelection(state: SignData, lineIndex: number) {
    if(this.editPickerInitialSelection != null) {
      this.editPickerInitialSelection = null;
    } else {
      this.editPickerInitialSelection = state;
    }
  }

  finalEditPickerSelection(state: SelectorState, lineIndex: number) {
    this.finalEditPickerSelectionChanged({letter: state.value, symbol: this.editPickerInitialSelection.symbol}, lineIndex);
    this.editPickerInitialSelection = null;
  }

  finalEditPickerSelectionChanged(state: SignData, lineIndex: number) {
    let old = this.activeEditSign

    this.activeEditSign.letter = state.letter;
    this.activeEditSign.symbol = state.symbol;
    this.notifyService.showInfo(`replaced ${old.symbol} (${old.letter}) with ${state.symbol} (${state.letter})`)
    this.activeEditSign.highlight = false;
    this.lineChanged.emit(lineIndex);
    this.activeEditSign = null;
    // MessageService sign replaced with ....
  }

  editPickerReplaceSign(state: SelectorState, lineIndex: number) {
    this.finalEditPickerSelectionChanged({letter: state.value, symbol: this.activeEditSign.symbol}, lineIndex)
  }

  editPickerSelectionChangeSmartSelector(state: SelectorState, lineIndex: number) {
    this.finalEditPickerSelectionChanged({letter: state.value, symbol: state.label}, lineIndex)
  }

  setAddToLineMode(lineIndex) {
    this.resetLineEditActions();
    this.activeAddSignPickerLineIndex = lineIndex;
  }

  setEditSignMode(lineIndex) {
    this.resetLineEditActions();
    this.activeSignEditorLineIndex = lineIndex;
  }

  setMarkSignMode(lineIndex) {
    this.resetLineEditActions();
    this.activeSignMarkLineIndex = lineIndex;
  }

  setRepredictSignMode(lineIndex) {
    this.resetLineEditActions();
    this.activeRepredictSignLineIndex = lineIndex;
  }

  setRemoveFromLineMode(lineIndex) {
    this.resetLineEditActions();
    this.activeSignDeleteLineIndex = lineIndex;
  }

  getCancelButtonIndex() {
    let indexes = [this.activeAddSignPickerLineIndex, this.activeSignEditorLineIndex,
                   this.activeSignDeleteLineIndex, this.activeSignMarkLineIndex,
                   this.activeRepredictSignLineIndex]
    return indexes.find(index => index != -1);
  }

  cancel() {
    this.resetLineEditActions();
  }

  resetLineEditActions() {
    if(this.activeEditSign) this.activeEditSign.highlight = false;
    this.activeAddSignPickerLineIndex = -1;
    this.activeSignEditorLineIndex = -1;
    this.activeSignDeleteLineIndex = -1;
    this.activeSignMarkLineIndex = -1;
    this.activeRepredictSignLineIndex = -1;
    this.activeEditSign = null;
    this.showAddLines = false;
    this.showAddCustomSign = false;
    this.editPickerInitialSelection = null;
  }

  startEditing() {
    this.isEditMode = true;
  }

  stopEditing() {
    this.resetLineEditActions();
    this.isEditMode = false;
  }

  setLetters(letters: Letter[][], originalTransliteration: string[] = null) {
    this.letters = letters;
    this.topLines = originalTransliteration
  }

  setTopLines(originalTransliteration: string[] = null) {
    this.topLines = originalTransliteration;
  }

  onLetterToggle(event) {
    if(event.event.buttons != 0) return;
    this.letterHover.emit(event);
  }

  onLetterClick(letter: Letter) {
    if(this.activeEditSign) {
      this.activeEditSign.highlight = false;
    }

    if(this.activeSignEditorLineIndex == letter.index.row || this.activeSignMarkLineIndex == letter.index.row) {
      this.activeEditSign = letter;
      if(this.activeSignEditorLineIndex == letter.index.row) {
        this.getSignPrediction.emit(letter);
      }
      this.activeEditSign.highlight = true;
    } else if(this.activeSignDeleteLineIndex == letter.index.row) {
      this.removeLetter(letter.index);
    } else if(this.activeRepredictSignLineIndex == letter.index.row) {
      this.repredictSign(letter);
    }
    else {
      this.letterClick.emit(letter.index);
    }
  }

  repredictSign(sign: Letter) {
    sign.loading = true;
    this.repredictSignEmitter.emit(sign);
  }

  isBadLine(index) {
    return this.badLines.some(badLine => badLine.index == index)
  }

  getBadLineMessage(lineIndex) {
    let badLine = this.badLines.find(badLine => badLine.index === lineIndex);
    let message = "";
    if(badLine.boxes != badLine.emptyLetters) {
      if(badLine.boxes == 0) {
        message += "Line doesn't exist.";
      } else {
        message += `There are ${badLine.boxes} bounding boxes and ${badLine.letters} signs.`;
      }
      
    }

    if(badLine.emptyLetters > 0) {
      if(badLine.emptyLetters == 1) {
        message += `\nThere is an empty sign.`;
      } else {
        message += `\nThere are ${badLine.emptyLetters} empty signs.`;
      }
    }

    return message;
  }

  getBorder(lineIndex) {
    return 'none';
  }

  getBackgroundColor(lineIndex) {
    return 'transparent';
  }

  hardReset() {
    this.letters = []
    this.badLines = []
    this.predictions = null;
    this.topLines = null;
    this.showAkkademiaIcon = false;
  }

  showActionButton() {
    return this.activeAddSignPickerLineIndex == -1 &&
            this.activeSignEditorLineIndex == -1 &&
            this.activeSignDeleteLineIndex == -1 &&
            this.activeSignMarkLineIndex == -1 &&
            this.activeRepredictSignLineIndex == -1;
  }

  spaceBetweenCancel() {
    if (this.activeSignEditorLineIndex != -1 ||
        this.activeSignDeleteLineIndex != -1 ||
        this.activeSignMarkLineIndex != -1) {
      if(this.activeEditSign == null) {
        return false;
      }
    } 
    return true;
      
  }

  setNewSelectedLetter(index: Index) {
    let newLetter = null;

    // unselect old letter if it exists
    if(this.selectedLetter) { 
      this.selectedLetter.selected = false;
    }

    if(index && this.letters && this.letters.length > index.row && this.letters[index.row].length > index.col) {
      // select new letter
      newLetter = this.letters[index.row][index.col];
      newLetter.selected = true;
      this.selectedLetter = newLetter;
    }

    if(this.predictions) {
      let newPrediction = null;

      if(this.selectedPrediction) {
        this.selectedPrediction.selected = false;
      }

      if(index && this.predictions.length > index.row && this.predictions[index.row].length > index.col) {
        // select new prediction
        newPrediction = this.predictions[index.row][index.col];
        newPrediction.selected = true;
        this.selectedPrediction = newPrediction;
      }
    }

  }
  
}

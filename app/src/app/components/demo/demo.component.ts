import { AfterContentChecked, AfterViewInit, ChangeDetectorRef, Component, Input, ViewChild } from '@angular/core';
import { saveAs } from 'file-saver';
import { MatButtonToggleGroup } from '@angular/material/button-toggle';
import { Image, Rect } from 'fabric/fabric-impl';
import { TokenStorageService } from 'src/app/auth/token-storage.service';
import { AmendmentStats, Dimensions, Index, Info, Letter, LetterDto, LetterHover, LetterView, LineError, LineStats, RectData } from 'src/app/models/letter';
import { AmendmentService } from 'src/app/services/amendment.service';
import { CanvasMode, CanvasType, FabricCanvasComponent } from '../fabric-canvas/fabric-canvas.component';

import { Router } from '@angular/router';
import { AuthService } from 'src/app/auth/auth.service';
import { NotificationService } from 'src/app/services/notification.service';
import { TextViewerComponent } from '../amendment/text-viewer/text-viewer.component';
import { SignData, LetterViewerComponent } from '../amendment/letter-viewer/letter-viewer.component';
import { CureSettings, Position } from '../amendment/amendment.component';
import { MatDialog } from '@angular/material/dialog';
import { DemoDialogContentComponent } from './dialog-content/demo-dialog-content.component';

@Component({
  selector: 'app-demo',
  templateUrl: './demo.component.html',
  styleUrls: ['./demo.component.scss']
})
export class DemoComponent implements AfterViewInit, AfterContentChecked {

  @ViewChild('canvas') canvas: FabricCanvasComponent;
  @ViewChild('transliterationTextViewer') transliterationsViewer: TextViewerComponent;
  @ViewChild('letterViewer', { static: false }) letterViewer: LetterViewerComponent;
  @ViewChild('actionGroup') actionGroup: MatButtonToggleGroup;

  @Input() public isDemoMode: boolean = false;

  public canvasType = CanvasType.Amendment;
  public settings: CureSettings = {useDetectron: true, detectronSensitivity: 0.5};

  private textId: string = null;
  public boundingBoxes: Rect[][] = [];
  public rectsForCanvas: Rect[] = [];

  public transliterations: Letter[][] = []; 
  public metadata: Info[];
  public backgroundImage: string;
  public labelToUnicode: SignData[] = [];
  public selectedFile: File = null;
  public signs: SignData[] = [];

  public unicodeToSigns: Map<string, string[]> = null;
  
  public generatedSigns: string[] = [];

  public textIsFixed = false;
  
  public requestedTextId: string = null;
  
  public badLines: LineError[] = [];
  public bBoxesForCombine: Rect[] = [];
  private resortBoxesAfterAdjust = false;

  public showInstructions: boolean = true;
  public showGetPredictions = true;

  public isSubmitLoading: boolean = false;
  public arePredictionsLoading: boolean = false;
  public isLoadingBoxes: boolean = false;


  public hoverLetter: Letter;
  public activeLetterIndex: Index;

  

  public stage: number = 0;

  constructor(private amendmentService: AmendmentService,
              private tokenStorageService: TokenStorageService,
              private cdref: ChangeDetectorRef,
              private router: Router,
              private authService: AuthService,
              private notifyService : NotificationService,
              public dialog: MatDialog) {
  }
  
  ngAfterViewInit() {
  }

  startStageOne() {
    this.stage = 1;
    this.canvas.props.canvasHeight = 1000;
    this.canvas.props.canvasWidth = 800;
    this.canvas.setCanvasSize();
    this.loadStageOne();
  }

  ngAfterContentChecked() {
    this.cdref.detectChanges();
  }

  modeChanged(val) {
    this.resetMode();
    this.handleAdjustMode();
  }

  handleAdjustMode() {
    if(this.resortBoxesAfterAdjust && this.canvas.selectedMode != CanvasMode.Adjust) {
      this.sortBoxes();
      this.resortBoxesAfterAdjust = false;
    }
    else if(this.canvas.selectedMode == CanvasMode.Adjust) {
      this.resortBoxesAfterAdjust = true;
    }
  }

  resetMode() {
    this.resetMarkedbBoxArray(this.bBoxesForCombine);
  }

  resetMarkedbBoxArray(array) {
    array.forEach(box =>{
      this.toggleBoxMarkForAction(box, false);
    })
    array = [];
  }

 
  boxSelectionChanged(index) {
    this.updateLetterViewerLetter(index);
    this.updateTextViewerLetters(index);
  }

  transliterationLetterHover(event: LetterHover) {
    if(event.active) {
      this.updateLetterViewerLetter(event.letterIndex)
      this.updateCanvasSelectedBox(event.letterIndex);
      this.updateTextViewerLetters(event.letterIndex);

    }
 
  }

  updateLetterViewerLetter(index: Index) {
    if(this.letterViewer == undefined) {
      return;
    }

    if(index == null) {
      return; // don't ruin current editing 
    }

    if(this.boundingBoxes.length <= index.row) {
      return
    }

    let transliterationLetter = null;
    if(this.transliterations && this.transliterations.length > index.row && this.transliterations[index.row].length > index.col) {
      transliterationLetter = this.transliterations[index.row][index.col];
    }

    let b = this.boundingBoxes[index.row][index.col]

    let letterView: LetterView = new LetterView();
    if(b && this.canvas.getCanvas() && this.canvas.getCanvas().backgroundImage) {
      letterView.imageData = ((this.canvas.getCanvas().backgroundImage as unknown) as Image).toDataURL({
        left: b.left, top: b.top, height: b.getScaledHeight(), width: b.getScaledWidth()})
      letterView.dimensions = new Dimensions(b.left, b.top, b.height, b.width);
    }
    
    this.letterViewer.setLetters(letterView, transliterationLetter);
    this.activeLetterIndex = index;
  }
  


  updateTextViewerLetters(index) {
    this.transliterationsViewer.setNewSelectedLetter(index);
  }

  updateCanvasSelectedBox(letterIndex: Index) {
    let row = letterIndex.row, col = letterIndex.col;
    let selectedRect = undefined;
    if(this.boundingBoxes.length > row && this.boundingBoxes[row].length > col) {
      selectedRect = this.boundingBoxes[row][col];
    }

    this.canvas.changeSelection(selectedRect);
  }

  boxDeleted(index) {
    this.boundingBoxes[index.row] = this.boundingBoxes[index.row].filter(item =>
                                    item.data.index != this.boundingBoxes[index.row][index.col].data.index);
    this.sortBoxes();
    this.deleteEmptyLines();
    this.updateCanvasStuffAfterAChange();
  
  }

  deleteEmptyLines() {
    this.boundingBoxes = this.boundingBoxes.filter(line => line.length > 0);
  }

  boxAdded(newRect: Rect) {
    this.sortBoxes();

    if(this.boundingBoxes.length > 0) {
      let closestLine = this.getClosestLineToRect(newRect)
      let positionComparedToLine = this.getRectPositionComparedToLine(newRect, closestLine);
      if(positionComparedToLine == Position.In) {
        this.addBoxToLine(newRect, closestLine);
      } else {
        this.addBoxToNewLine(newRect, closestLine.index, positionComparedToLine);
      }
    } else {
      let newIndex = new Index(0, 0);
      newRect.data = new RectData(newIndex);
      this.boundingBoxes.push([newRect]);
    }
   
    this.updateCanvasStuffAfterAChange();
  }

  addBoxToNewLine(newRect: Rect, closestLineIndex: number, positionComparedToLine: Position) {
    let lineIndex = closestLineIndex + 1; // for when box top is under line top
    if(positionComparedToLine == Position.OnTop) { // if bottom top is higher than line top
      lineIndex = closestLineIndex;
    }
    let newIndex = new Index(lineIndex, 0);
    newRect.data = new RectData(newIndex);
    this.boundingBoxes.splice(lineIndex, 0, [newRect])
  }

  addBoxToLine(newRect: Rect, closestLine: LineStats) {
    let indexInLine = this.getRectIndexInLine(newRect, closestLine.index);
    let newIndex = new Index(closestLine.index, indexInLine);
    newRect.data = new RectData(newIndex);
    let itemsToRemoveAmount = 0;
    this.boundingBoxes[closestLine.index].splice(indexInLine, itemsToRemoveAmount, newRect);
  }

  boxMarkToggle(index) {
    let box = this.boundingBoxes[index.row][index.col]

    if(this.canvas.selectedMode == CanvasMode.Combine) {
      if(box.data.selectedForAction) {
        let boxIndex = this.bBoxesForCombine.indexOf(box);
        if(boxIndex == 0 || boxIndex == this.bBoxesForCombine.length - 1) {
          this.unmarkBoxForCombine(box);
        } else { // if we remove center box it would cause not-close boxes combine so we need to unmark all
          this.bBoxesForCombine.forEach(box => {
            this.unmarkBoxForCombine(box);
          })
        }
        
      } else {
        if(this.bBoxesForCombine.length == 0) {
          this.markBoxForCombine(box);
        } else {
          if(this.bBoxesForCombine[0].data.index.row == box.data.index.row &&
            this.bBoxesForCombine.some(item => Math.abs(item.data.index.col - box.data.index.col) == 1)) {
            this.markBoxForCombine(box);
            this.bBoxesForCombine.sort((box, otherBox) => box.data.index.col < otherBox.data.index.col ? -1 : 1);
          } 
        }
      } 
    } else if(this.canvas.selectedMode == CanvasMode.Mark) {
      if(box.data.selectedForAction) {
        this.toggleBoxMarkForAction(box, false);
      } else {
        this.toggleBoxMarkForAction(box, true);
      }
    }

    
  }

  markBoxForCombine(box) {
    this.bBoxesForCombine.push(box);
    this.toggleBoxMarkForAction(box, true);
  }

  unmarkBoxForCombine(box) {
    this.bBoxesForCombine = this.bBoxesForCombine.filter(item => item !== box);
    this.toggleBoxMarkForAction(box, false);
  }

  toggleBoxMarkForAction(box, isMark: boolean) {
    box.data.selectedForAction = isMark; 
    this.canvas.markBoxForAction(box, isMark);
  }

  combineBoxes() {
    if(this.bBoxesForCombine.length > 1) {
      this.canvas.combineBoxes(this.bBoxesForCombine);
      this.bBoxesForCombine = [];
    }
  }

  repredictBoxes(sign: Letter, onlySuggest = false) {
    if(this.boundingBoxes.length > sign.index.row && this.boundingBoxes[sign.index.row].length > sign.index.col) {
      const box = this.boundingBoxes[sign.index.row][sign.index.col];
      const dimensions = [new Dimensions(box.left, box.top, box.getScaledHeight(), box.getScaledWidth(), box.data.index)];
    
      this.amendmentService.getSpecificPredictions(this.textId, dimensions).subscribe(
        data => {
          data.forEach(predictionList => {
            let firstPred =  predictionList[0].letter
            if(onlySuggest) {
              this.transliterations[firstPred.index.row][firstPred.index.col].predictions = predictionList;
            } else {
              this.transliterations[firstPred.index.row][firstPred.index.col] = firstPred;
            }
          })
        }, error => {}
      );
    }
  }


  setPredictionsRightness(predictions: Letter[][]) {
    for (let row = 0; row < this.transliterations.length; row++) {
      for (let col = 0; col < this.transliterations[row].length; col++) {
        try {
          if(this.transliterations[row][col].symbol != predictions[row][col].symbol) {
            predictions[row][col].wrong = true;
          } else {
            predictions[row][col].right = true;
          }
        } catch {
          //console.log("error")
        }
      }
    }
  }

  sortBoxes() {
    this.boundingBoxes.forEach(line => {
      line.sort((a: Rect, b: Rect) => a.left - b.left);
    })
    this.updateBoundingBoxesIndexes()
  }


  getRectIndexInLine(newRect: Rect, lineIndex: number) {
    let index =  this.boundingBoxes[lineIndex].findIndex(box => newRect.left <= box.left);
    if(index == -1) {
      index = this.boundingBoxes[lineIndex].length;
    }
    return index;
  }

  getLinesAvgs(): LineStats[] {
    let lineAvgs = [];

    this.boundingBoxes.forEach((line, index) => {
      let lineTopSum = 0;
      let lineBottomSum = 0;
      line.forEach(box => {
        lineTopSum += box.top;
        lineBottomSum += box.top + box.getScaledHeight()
      });

      let lastBoxInLine = line[line.length - 1];
      let lineLeftEnd = lastBoxInLine.left + lastBoxInLine.getScaledWidth();

      lineAvgs.push(new LineStats(lineTopSum / line.length, lineBottomSum / line.length, lineLeftEnd,  index));
    });

    return lineAvgs;
  }

  getClosestLineToRect(rect: Rect) {
    
    let lineAvgs = this.getLinesAvgs();

    let boxTop = rect.top;

    // sort lines by their top distance to box top
    lineAvgs.sort((a, b) => {
      return Math.abs(a.topAvg - boxTop) - Math.abs(b.topAvg - boxTop);
    });
    
    // make sure box is in line
    return lineAvgs[0];
  }

  getRectPositionComparedToLine(rect: Rect, line: LineStats) {
    // if box is under line top (lets check if its under/almost under the line)
    let lineHeight = line.bottomAvg - line.topAvg;
    if(rect.top > line.topAvg) {
      // //console.log("check for rect that is bottom of line")
      // if box top is under line bottom or box top is very close to line bottom
      if(rect.top > line.bottomAvg || line.bottomAvg - rect.top < 0.35 * lineHeight) {
        // //console.log("box cant be in this line, its too low")
        return Position.Under;
      }
    } else {
      // //console.log("check for rect in top of line")

      // box top is higher than the line top, lets check if its totally/almost on top
      let rectBottom = rect.top + rect.getScaledHeight();
      if(rectBottom < line.topAvg || rectBottom - line.topAvg < 0.35 * lineHeight) {
        // //console.log("box cant be in this line, its too high")
        return Position.OnTop;
      }
    }
    return Position.In;
  }

  loadSigns() {
    if(this.signs.length != 0) {
      return;
    }
    
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

  generateBoundingBoxes() {
    this.isLoadingBoxes = true;
    setTimeout(() => 
    {
      this.canvas.addRectangles(this.rectsForCanvas);
      this.isLoadingBoxes = false;
      this.notifyService.showSuccess("Loaded bounding boxes");
      this.stage = 3;
    },
    1000);
  }

  startFixingBoxes() {
    this.stage = 4;
    this.canvasType = CanvasType.Amendment;
    this.canvas.canvasType = this.canvasType;
    this.canvas.updateActionsAccordingToType();
  }

  generateTransliterations() {
    this.stage = 5;
    this.openDialog();
    this.getPredictions();
  }

  loadStageOne() {
    this.loadSigns();
    this.resetStuff()
    this.notifyService.showInfo("Loading text... Please wait about 20 seconds till the AI is up for you...", 20000)
    this.amendmentService.getStageOne(this.settings).subscribe(
      data => {
        if(data) {

          this.textId = data.text_id;
          this.initCanvasType();
          this.fetchImage(data.text_id);
          this.fetchBoundingBoxes(data.dimensions);
          this.fetchMetadata(data.metadata);
          this.updateCanvasStuffAfterAChange();
          this.notifyService.showSuccess(`Text ${data.text_id} loaded`)
        }
      }, error => {
        //console.log(error);
        this.notifyService.showError(`Loading text failed ${error.statusText}`)
      }
    )
  }

  initCanvasType() {
    this.canvasType = CanvasType.ViewAmendment;
    this.canvas.canvasType = this.canvasType;
    this.canvas.updateActionsAccordingToType();
    this.transliterationsViewer.canEdit = !this.textIsFixed;
  }

  resetStuff() {
    this.metadata = [];
    this.activeLetterIndex = null;
    this.showGetPredictions = true;
    this.textIsFixed = false;
    this.canvas.hardReset();
  }

  fetchMetadata(metadata: Object[]) {
    let infos: Info[] = [];
    if(!metadata) {
      return;
    }

    metadata.forEach(meta => {
      for (const [key, value] of Object.entries(meta)) {
        if(key == "Is fixed" && value == true) {
          this.textIsFixed = true;
        }
        infos.push(new Info(key, value));
      }
    })
    
    this.metadata = infos;
  }

  fetchTransliteration(transliteration: Letter[][], originalTransliteration: string[]) {
    this.transliterationsViewer.hardReset();
    
    if(transliteration == null) {
      this.transliterations = [];
      return;
    }

    let nonEmptyTransliteration = [];
    transliteration.forEach(line => {
      nonEmptyTransliteration.push(line.filter(letter => letter.letter != ""))
    })

    nonEmptyTransliteration = this.addIndexes(nonEmptyTransliteration);

    this.transliterations = nonEmptyTransliteration;
    this.transliterationsViewer.setLetters(nonEmptyTransliteration, originalTransliteration);
    this.transliterationsViewer.lettersArePredictions = true;
  }

  fetchImage(imageName: string, file: File = null) {
    let imageToShow: any;
    let reader = new FileReader();
        reader.addEventListener("load", () => {
          imageToShow = reader.result;   
          this.canvas.props.canvasImage = imageToShow;
          this.backgroundImage = imageToShow;
          this.canvas.setCanvasImage();
          this.canvas.props.canvasHeight = 650;
          this.canvas.setCanvasSize();
        }, false);

    if(file) {
      reader.readAsDataURL(file); 
    } else {
      this.amendmentService.getImage(imageName).subscribe(
        data => {
          reader.readAsDataURL(data);   
        }, error => {
          this.notifyService.showError(`failed to fetch text image ${error}`)
        }
      )
    }
  }

  fetchBoundingBoxes(allDimensions: Dimensions[][] = []) {
    let rectsForCanvas = []
    let boundingBoxes = [];

    let row = 0;
    let col = 0;
    for(let line of allDimensions) {
      col = 0;
      let boundingBoxesLine = [];
      for(let dimensions of line) {
        if(dimensions) {
          let rect = this.canvas.makeRectangle(dimensions.x, dimensions.y, dimensions.width, dimensions.height,
            this.canvas.DEFAULT_RECT_FILL, 'blue', true, new Index(row, col++), true)
  
          boundingBoxesLine.push(rect);
          rectsForCanvas.push(rect);
        }
      }
      row++;

      boundingBoxes.push(boundingBoxesLine);
    }

    this.boundingBoxes = boundingBoxes;
    this.rectsForCanvas = rectsForCanvas;
    // this.updateLetterViewerLetter(new Index(0, 0)); 
    // this.canvas.addRectangles(rectsForCanvas);
  }

  updateCanvasBoundingBoxesLines() {
    let lines = this.getLinesAvgs();
    this.canvas.updateLines(lines);
  }

  addIndexes(letters: Letter[][]) {
    for (let row = 0; row < letters.length; row++) {
      for (let col = 0; col < letters[row].length; col++) {
        letters[row][col].index = new Index(row, col);
      }
    }

    return letters;
  }

  getPredictions() {
    let dimensions = [];
    this.boundingBoxes.forEach(line => {
      let dimensionsLine = []
      line.forEach(box => {
        dimensionsLine.push(new Dimensions(box.left, box.top, box.getScaledHeight(), box.getScaledWidth()))
      })
      dimensions.push(dimensionsLine);
    })
    
    this.arePredictionsLoading = true;
    this.amendmentService.getPredictions(this.textId, dimensions).subscribe(
      data => {
        this.arePredictionsLoading = false;
        this.generatedSigns = data.sign_translation;
        this.fetchTransliteration(data.predictions, data.sign_translation)
        this.transliterationsViewer.title = "AI generated transliterations"
        this.showGetPredictions = false;
        this.notifyService.showSuccess(`Transliterations genereated by the AI`)
      }, error => {}
    );
  }

  updateCanvasStuffAfterAChange() {
    this.updateBadLines();
    this.updateBoundingBoxesIndexes();
    this.updateCanvasBoundingBoxesLines()
  }

  updateBadLines() {
    this.badLines = [];
    for (let index = 0; index < this.transliterations.length; index++) {
      const line = this.transliterations[index];
      const emptyLettersAmount = line.filter(letter => letter.letter == "").length
      const letterAmount = line.length;
      const boxAmount = this.boundingBoxes.length > index ? this.boundingBoxes[index].length : 0;

      if(letterAmount != boxAmount || emptyLettersAmount > 0) {
        this.badLines.push(new LineError(index, boxAmount, letterAmount, emptyLettersAmount));
      } 
    }
  }

  transliterationChanged(lineIndex) {
    this.updateTransliterationStuffAfterAChange();
  }

  updateTransliterationStuffAfterAChange() {
    this.updateTransliterationIndexes();
    this.updateBadLines();
  }

  updateTransliterationIndexes() {
    this.transliterations.forEach((line, row) => {
      line.forEach((sign, col) => {
        sign.index = new Index(row, col);
      })
    });
  }

  updateBoundingBoxesIndexes() {
    this.boundingBoxes.forEach((line, row) => {
      line.forEach((box, col) => {
        box.data = new RectData(new Index(row, col));
      })
    });
  }


  isSubmitAvailable() {
    //console.log("fire")
    if(!this.transliterations || this.transliterations.length == 0) {
      return false;
    }

    if(this.badLines.length != 0) {
      return false;
    }
    
    return true;
  }

  openDialog() {
    const dialogRef = this.dialog.open(DemoDialogContentComponent);

    dialogRef.afterClosed().subscribe(result => {
      console.log(`Dialog result: ${result}`);
    });
  }

  startOver() {
    this.resetStuff();
    this.stage = 0;
  }

  exportResult() {
    var lines = `Text: ${this.textId}\n\n`;
    lines += `Image url: ${this.amendmentService.getImageUrl(this.textId)}\n\n`;

    lines += "\nUnicodes predicted by CuRe:\n\n"
    this.transliterations.forEach(line => {
      lines += line.map(letter => this.getLetterView(letter.symbol, letter)).join(" ") + "\n";
    })

    lines += "Transliterations generated by Akkdemia (using CuRe unicode predictions):\n\n"
    this.generatedSigns.forEach(line => {
      lines += line + "\n";
    })

    var transliteratinsBlob = new Blob([lines], {type: "text/plain;charset=utf-8"});
    saveAs(transliteratinsBlob, `Text ${this.textId}.txt`);
  }

  getLetterView(view: string, letter: Letter) {
    if(view == "") {
      return "NONE";
    }

    if(letter.certainty) {
      view += letter.certainty;
    }
    return view;
    
  }


}


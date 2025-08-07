import { AfterContentChecked, AfterViewInit, ChangeDetectorRef, Component, Inject, Input, OnInit, Output, SkipSelf, ViewChild } from '@angular/core';
import { MatButtonToggleGroup } from '@angular/material/button-toggle';
import { Image, Rect } from 'fabric/fabric-impl';
import { TokenStorageService } from 'src/app/auth/token-storage.service';
import { AmendmentStats, Dimensions, Index, Info, Letter, LetterDto, LetterHover, LetterView, LineError, LineStats, RectData } from 'src/app/models/letter';
import { AmendmentService } from 'src/app/services/amendment.service';
import { CanvasMode, CanvasType, FabricCanvasComponent } from '../fabric-canvas/fabric-canvas.component';
import { TextViewerComponent } from './text-viewer/text-viewer.component';
import { SignData, LetterViewerComponent } from './letter-viewer/letter-viewer.component';
import { ActivatedRoute, Router } from '@angular/router';
import { AuthService } from 'src/app/auth/auth.service';
import { NotificationService } from 'src/app/services/notification.service';
import { saveAs } from 'file-saver';

import { MatDialog, MatDialogRef, MAT_DIALOG_DATA } from '@angular/material/dialog';
import { CuredComponent } from '../cure-d/cured.component';
import { TextCreatorComponent } from '../common/text-creator/text-creator.component';
import { MetaViewerComponent } from './meta-viewer/meta-viewer.component';

export enum Position {
  OnTop = "OnTop",
  In = "In",
  Under = "Under"
}

@Component({
  selector: 'amendment-page',
  templateUrl: './amendment.component.html',
  styleUrls: ['./amendment.component.scss']
})
export class AmendmentComponent implements OnInit, AfterViewInit, AfterContentChecked  {

  @ViewChild('canvas') canvas: FabricCanvasComponent;
  @ViewChild('transliterationTextViewer') transliterationsViewer: TextViewerComponent;
  @ViewChild('letterViewer', { static: false }) letterViewer: LetterViewerComponent;
  @ViewChild('actionGroup') actionGroup: MatButtonToggleGroup;

  public settings: CureSettings = {useDetectron: true, detectronSensitivity: 0.5};

  @Input() public isDemoMode: boolean = false;

  public canvasType = CanvasType.Amendment;
  CURE_SETTINGS = 'cure-settings';

  private textId: string = null;
  public boundingBoxes: Rect[][] = [];
  public transliterations: Letter[][] = []; 
  public metadata: Info[];
  public backgroundImage: string;
  public labelToUnicode: SignData[] = [];
  public unicodeToSigns: Map<string, string[]> = null;

  public selectedFile: File = null;
  public signs: SignData[] = [];

  public textIsFixed = false;
  public isTextWithTransliterations = false;
  
  public requestedTextId: string = null;
  public highlightQuerySymbol: string = null;
  
  public badLines: LineError[] = [];
  public bBoxesForCombine: Rect[] = [];
  private resortBoxesAfterAdjust = false;

  public showInstructions: boolean = true;
  public showGetPredictions = true;

  public isSubmitLoading: boolean = false;
  public arePredictionsLoading: boolean = false;
  public showLoadingCanvas: boolean = false;

  public hoverLetter: Letter;
  public activeLetterIndex: Index;

  constructor(private amendmentService: AmendmentService,
              private tokenStorageService: TokenStorageService,
              private cdref: ChangeDetectorRef,
              private router: Router,
              private route: ActivatedRoute,
              private authService: AuthService,
              private notifyService : NotificationService,
              public dialog: MatDialog) {
  }

  ngOnInit(): void {
    const textId: string = this.route.snapshot.queryParamMap.get('textId');
    const query: string = this.route.snapshot.queryParamMap.get('query');
    if(textId != null) {
      this.requestedTextId = textId;
      this.highlightQuerySymbol = query;
    }
  }

  public loadSettings() {
    try {
      if(localStorage.getItem(this.CURE_SETTINGS) != null) {
        this.settings = JSON.parse(localStorage.getItem(this.CURE_SETTINGS));
      }
    } catch(e) {

    }
  }


  ngAfterViewInit() {
    this.loadSettings();

    this.canvas.props.canvasHeight = 1000;
    this.canvas.props.canvasWidth = 800;
    this.canvas.setCanvasSize();

    this.loadStageOne(this.requestedTextId != null);
  }

  ngAfterContentChecked() {
    this.cdref.detectChanges();
  }

  modeChanged(val) {
    this.resetMode();
    this.handleAdjustMode();
  }

  showMetadata() {
    const dialogRef = this.dialog.open(MetaViewerComponent);
    dialogRef.componentInstance.metadata = this.metadata;
  }

  findText() {
    const dialogRef = this.dialog.open(TextCreatorComponent);
    dialogRef.componentInstance.selectTransliteration = true;
    dialogRef.componentInstance.showCreateOnNoResult = false;
    dialogRef.afterClosed().subscribe(result => {
      if(result) {
        this.textId = result[0];
        // this.transliterationId = result[1];
        // this.isLoadedFromServer = true;
        // this.loadImageFromServer();
        // this.loadTransliteration();
      } else {
        // this.stage = 0;
      }

    });
  }

  readPDFFile(event){
    // PDFJS.getDocument({data: pdf}).then(function(pdf){
    //   var pdfPages = pdf.pdfInfo.numPages;
    //   console.log(pdfPages); 
    // }); 

    // const file:File = event.target.files[0];
    // var fileReader = new FileReader();

    // fileReader.onload = function(e){ 
    //   readPDFFile(new Uint8Array(e.target.result)); 
    // };

    // fileReader.readAsArrayBuffer(file); 
    
  }
  

  onFileSelected(event) {
    const file:File = event.target.files[0];

    if (file) {
      this.loadStageOne(false, file);
    }
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
      if(this.highlightQuerySymbol) { // first hover won't delete highlight
        this.highlightQuerySymbol = null;
        return;
      }

      this.updateLetterViewerLetter(event.letterIndex)
      this.updateCanvasSelectedBox(event.letterIndex);
      this.updateTextViewerLetters(event.letterIndex);

    }
 
  }

  updateLetterViewerLetter(index: Index) {

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

  setActiveBySymbol(symbol: string) {
    // find symbol in transliteration
    let index = null; 
    this.transliterations.forEach((row, rowIndex) => {
      row.forEach((letter, letterIndex) => {
        if(letter.symbol == symbol) {
          index = new Index(rowIndex, letterIndex);
        }
      })
    })

    if(index != null) {
      this.updateLetterViewerLetter(index);
      this.updateCanvasSelectedBox(index);
      this.updateTextViewerLetters(index);
    }
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

  generateBoxesJson() {
    let dimensions = [];
    this.boundingBoxes.forEach(line => {
      let dimensionsLine = []
      line.forEach(box => {
        dimensionsLine.push(new Dimensions(box.left, box.top, box.getScaledHeight(), box.getScaledWidth()))
      })
      dimensions.push(dimensionsLine);
    })

    let obj = {"boxes": dimensions};

    return JSON.stringify(obj);
  }

  exportBoxes() {
    let json = this.generateBoxesJson();

    var transliteratinsBlob = new Blob([json], {type: "application/json;charset=utf-8"});
    saveAs(transliteratinsBlob, `${this.textId}_boxes.json`);
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

  regenerateBoxes() {
    this.activeLetterIndex = null;
    if(this.boundingBoxes.length > 0 && !confirm("Generate boxes will erase existing boxes, are you sure?")) {
     return;
    }
    this.canvas.removeAllRects();
    this.showLoadingCanvas = true;
    if(this.settings.useDetectron) {
      this.notifyService.showInfo("Generating boxes... Please allow the Detectron AI up to 20 seconds...", 20000)
    }
    this.amendmentService.generateBoxes(this.settings, this.textId).subscribe(
      data => {
        if(data.length == 0) {
          this.notifyService.showWarning("AI failed to detect boxes, try using Detectron...", 15000);
        }
        this.showLoadingCanvas = false;
        this.fetchBoundingBoxes(data);
        this.updateCanvasStuffAfterAChange();
      }
    );
  }

  loadStageOne(useRequestedId = false, file: File=null) {
    this.loadSigns();
    this.resetStuff()
    
    const requestedId = useRequestedId ? this.requestedTextId : "";
    this.showLoadingCanvas = true;
    if(this.settings.useDetectron) {
      this.notifyService.showInfo("Loading text... Please allow the Detectron AI up to 20 seconds...", 20000)
    }
    this.amendmentService.getStageOne(this.settings, this.textId, requestedId, file).subscribe(
      data => {
        this.showLoadingCanvas = false;
        if(data) {
          if(file) {
            this.notifyService.showSuccess(`Uploaded ${file.name} to the server`)
          }

          this.isTextWithTransliterations = file == null && data.transliteration != null;
          this.textId = data.text_id;
          this.fetchIsTextFixed(data.is_fixed);
          this.fetchImage(data.text_id, file);
          this.fetchBoundingBoxes(data.dimensions);
          this.fetchTransliteration(data.transliteration, null);
          this.fetchMetadata(data.metadata);
          this.fetchAkkademia(data.akkademia);
          this.updateCanvasStuffAfterAChange();
          if(this.highlightQuerySymbol) {
            this.setActiveBySymbol(this.highlightQuerySymbol);
          }
          this.notifyService.showSuccess(`Text ${data.text_id} loaded`)
        }
      }, error => {
        //console.log(error);
        this.notifyService.showError(`Loading text failed ${error.statusText}`)
      }
    )
  }

  fetchAkkademia(akkademia: string[]) {
    if(akkademia && akkademia.length > 0) {
      this.transliterationsViewer.topLines = akkademia;
    }
  }

  fetchIsTextFixed(isFixed) {
    this.textIsFixed = isFixed;
    if(this.textIsFixed) {
      this.canvasType = CanvasType.ViewAmendment;
      
    } else {
      this.canvasType = CanvasType.Amendment;
    }
    this.canvas.canvasType = this.canvasType;
    this.canvas.updateActionsAccordingToType();
    this.transliterationsViewer.canEdit = !this.textIsFixed;
  }

  resetStuff() {
    this.metadata = [];
    this.isTextWithTransliterations = true;
    this.showGetPredictions = true;
    this.textIsFixed = false;
    this.activeLetterIndex = null;
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

  detectronSettings() {
    const dialogRef = this.dialog.open(SettingsDialog, {
      data: this.settings
    });
    dialogRef.componentInstance.boundingBoxes = this.boundingBoxes;


    dialogRef.afterClosed().subscribe(result => {
      console.log(result);
      if(result.event == 'loadBoxes'){
        this.fetchBoundingBoxes(result.data);
        this.updateCanvasStuffAfterAChange();
      } else if(result.event == 'clearBoxes') {
        this.boundingBoxes = [];
        this.canvas.removeAllRects()
        this.sortBoxes();
        this.deleteEmptyLines();
        this.updateCanvasStuffAfterAChange();
        this.updateTransliterationStuffAfterAChange();
      } else if(result.event == 'exportBoxes') {
        this.exportBoxes();
      } else if(result.event == 'exportText') {
        this.exportAll();
      }
    });
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
    // this.updateLetterViewerLetter(new Index(0, 0)); 
    this.canvas.addRectangles(rectsForCanvas);
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

  exportAll() {
    var lines = `Text: ${this.textId}\n\n`;
    lines += `Image url: ${this.amendmentService.getImageUrl(this.textId)}\n\n`;

    lines += "\nUnicodes predicted by CuRe:\n\n"
    this.transliterations.forEach(line => {
      lines += line.map(letter => this.getLetterView(letter.symbol, letter)).join(" ") + "\n";
    })

    if(this.transliterationsViewer.topLines) {
      lines += "\nAkkademia transliterations:\n\n"
      this.transliterationsViewer.topLines.forEach(line => {
        lines += line + "\n";
      })
    }

    if(this.transliterationsViewer.letters) {
      lines += "\nTransliterations:\n\n"
      this.transliterationsViewer.letters.forEach(line => {
        let newLine = "";
        line.forEach(letter => {
          newLine += letter.letter + " "
        })
        lines += newLine + "\n";
      })
    }

    if(this.transliterationsViewer.predictions) {
      lines += "\nCure Predictions:\n\n"
      this.transliterationsViewer.predictions.forEach(line => {
        let newLine = "";
        line.forEach(letter => {
          newLine += letter.letter + " "
        })
        lines += newLine + "\n";
      })
    }

    lines += "\n Bounding boxes json:\n\n";
    lines += this.generateBoxesJson();

    // lines += "Transliterations generated by Akkdemia (using CuRe unicode predictions):\n\n"
    // this.generatedSigns.forEach(line => {
    //   lines += line + "\n";
    // })

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

  getPredictions() {
    if(this.transliterations && this.badLines.length != 0) {
      this.notifyService.showWarning("Please match bounding boxes to transliterations first");
      return;
    }
    let error = false;
    let dimensions = [];
    this.boundingBoxes.forEach((line, lineIndex) => {
      let dimensionsLine = []
      line.forEach((box, boxIndex) => {
        let left = box.left;
        let top = box.top;
        let height = box.getScaledHeight();
        let width = box.getScaledWidth();
        if(left < 0 || top < 0 || height < 0 || width < 0) {
          this.notifyService.showError(`Box at line ${lineIndex+1}, number ${boxIndex+1} (line has ${line.length} boxes) has negative one/some values left: ${left} top: ${top} height: ${height} width: ${width}, remove it and add again`, 15000);
          error = true;
          return;
        }
        dimensionsLine.push(new Dimensions(left, top, height, width))
      })
      dimensions.push(dimensionsLine);
    })

    if(error) {
      return;
    }
    
    this.arePredictionsLoading = true;
    if(this.boundingBoxes.length == 0) {
      this.showLoadingCanvas = true;
    }
    this.amendmentService.getPredictions(this.textId, dimensions).subscribe(
      data => {
        this.arePredictionsLoading = false;
        this.showLoadingCanvas = false;
        if(this.isTextWithTransliterations) {
          let predicitons = this.addIndexes(data.predictions);
          this.setPredictionsRightness(predicitons);
          this.transliterationsViewer.predictions = predicitons;
          this.transliterationsViewer.topLines = data.sign_translation;
          this.transliterationsViewer.showAkkademiaIcon = true;
        } else {
          this.fetchTransliteration(data.predictions, data.sign_translation)
          this.transliterationsViewer.title = "AI generated transliterations"
          this.isTextWithTransliterations = true;
          this.showGetPredictions = false;
          this.notifyService.showSuccess(`Transliterations genereated by the AI`)
        }

      }, error => {}
    );


  }

  submitAll() {
    this.updateBadLines();
    if(!this.isSubmitAvailable()) {
      this.notifyService.showWarning("You can't submit yet, fix bad lines first")
      return;
    }

    let self = this;
    let result = [];
    this.transliterations.forEach((line, row) => {
      let resultLine = [];
      line.forEach((trans, col) => {
        trans.dimensions = Dimensions.fromRect(self.boundingBoxes[row][col]);
        resultLine.push(LetterDto.fromLetter(trans));
      });
      result.push(resultLine);
    })
    
    this.saveText(result, true);
  }

  saveText(result: LetterDto[][], isFixed=true) {
    this.isSubmitLoading = true;
    let akkademiaLines = this.transliterationsViewer.topLines;
    if (!akkademiaLines) {
      akkademiaLines = [];
    }
    this.amendmentService.postSubmit(this.textId, result, akkademiaLines, isFixed).subscribe(data => {
      let stats = data as AmendmentStats;
      this.isSubmitLoading = false;
      if(isFixed) {
        this.notifyService.showSuccess(`Great job!\n ${stats.saved_signs} signs saved successfully\nTotal completed texts: ${stats.completed_texts}\nTotal signs: ${stats.saved_signs}`)
        this.textIsFixed = true;
      } else {
        this.notifyService.showSuccess(`Thanks!\n Text ${this.textId} saved successfully`)
      }
    });
  }

  setInProgress() {
    this.amendmentService.setInProgress(this.textId).subscribe(data => {
      this.notifyService.showSuccess(`Text ${this.textId} is now in progress`)
      this.textIsFixed = false;
    });
  }

  saveWorkInProgress() {
    let result = [];
    let lineAmount = Math.max(this.transliterations.length, this.boundingBoxes.length);
    
    for (let lineIndex = 0; lineIndex < lineAmount; lineIndex++) {
      let newLine = [];
      let transLine = this.transliterations.length > lineIndex ? this.transliterations[lineIndex] : [];
      let boxLine = this.boundingBoxes.length > lineIndex ? this.boundingBoxes[lineIndex] : [];
      let itemAmount = Math.max(transLine.length, boxLine.length);

      for (let itemIndex = 0; itemIndex < itemAmount; itemIndex++) {
        let transItem = transLine.length > itemIndex ? transLine[itemIndex] : null;
        let boxItem = boxLine.length > itemIndex ? boxLine[itemIndex] : null;
        
        let letterSymbol = "", letterSign = "", letterCertrainity = "";
        if(transItem) {
          letterSign = transItem.letter;
          letterSymbol = transItem.symbol;
          letterCertrainity = transItem.certainty;
        }
        let letterDimensions = boxItem ? Dimensions.fromRect(boxItem) : null;
        
        let newLetter = new LetterDto(letterSign, letterSymbol, letterCertrainity, letterDimensions);
        newLine.push(newLetter);
      }

      result.push(newLine);
    }

    this.saveText(result, false);

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

  uploadPdf() {
    const dialogRef = this.dialog.open(CuredComponent);

    dialogRef.afterClosed().subscribe(result => {
    //   let selectedPdf = result as SelectedPdf;
    //   console.log(result as SelectedPdf);

    //   let reader = new FileReader();
    //   reader.addEventListener("load", () => {
    //     let imageToShow: any = reader.result;
    //     this.canvas.props.canvasImage = imageToShow;
    //     this.backgroundImage = imageToShow;
    //     this.canvas.setCanvasImage();
    //     this.canvas.props.canvasHeight = 650;
    //     this.canvas.setCanvasSize();
    //   }, false);

    //   this.amendmentService.postPdf(selectedPdf).subscribe(result => {
    //     if(result) {
    //       reader.readAsDataURL(result); 
    //     }
    //   });
    // });
    });
  }

}

export interface CureSettings {
  useDetectron: boolean;
  detectronSensitivity: number;
}

@Component({
  selector: 'cure-settings',
  templateUrl: 'cure-settings.html',
})
export class SettingsDialog {
  CURE_SETTINGS = 'cure-settings';

  constructor(@Inject(MAT_DIALOG_DATA) public data: CureSettings,
  public dialogRef: MatDialogRef<SettingsDialog>,
  ) {}

  
  @Input() public boundingBoxes: Rect[][] = [];

  public save() {
    localStorage.removeItem(this.CURE_SETTINGS);
    localStorage.setItem(this.CURE_SETTINGS, JSON.stringify(this.data));
  }

  exportBoxes() {
    this.dialogRef.close({event:"exportBoxes"});
  }

  exportAll() {
    this.dialogRef.close({event:"exportText"});

  }

  cleanBoxes() {
    if(!confirm("are you sure you want to clear boxes?")) {
      return;
    }

    this.dialogRef.close({event:"clearBoxes"});

  }


  onJsonSelected(event) {
    const file:File = event.target.files[0];

    if (file) {
      let fileReader = new FileReader();
      fileReader.addEventListener("load", () => {
        let rawJson: any = fileReader.result;
        let obj = JSON.parse(rawJson);
        this.dialogRef.close({event:"loadBoxes", data: obj.boxes});
      }, false);

      fileReader.readAsText(file);

    }
  }

}
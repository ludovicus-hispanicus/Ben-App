import { AfterViewInit, Component, OnInit, ViewChild } from '@angular/core';
import { Image as FabricImage, Rect } from 'fabric/fabric-impl';
import { PDFDocumentProxy } from 'ng2-pdf-viewer';
import { Dimensions, Index, Letter, LetterHover, RectData } from 'src/app/models/letter';
import { CuredService } from 'src/app/services/cured.service';
import { NotificationService } from 'src/app/services/notification.service';
import { CanvasMode, CanvasType, FabricCanvasComponent } from '../fabric-canvas/fabric-canvas.component';
import { saveAs } from 'file-saver';
import { LineEditorComponent } from './line-editor/line-editor.component';
import { MatDialog } from '@angular/material/dialog';
import { TextCreatorComponent } from '../common/text-creator/text-creator.component';
import { AuthService } from 'src/app/auth/auth.service';
import { ActivatedRoute } from '@angular/router';

export class SelectedPdf {
  constructor(public pdf: File,
              public page: number) {}
}

@Component({
  selector: 'cured',
  templateUrl: './cured.component.html',
  styleUrls: ['./cured.component.scss']
})
export class CuredComponent implements OnInit, AfterViewInit {
  public options = {
    density: 100,
    saveFilename: "untitled",
    savePath: "./images",
    format: "png",
    width: 600,
    height: 600
  };

  public stage = 0;

  public pdfSrc = null;
  public pdfFile = null;

  public currentpage = 1;
  public totalPages;
  public isCropImage = false;
  public result: SelectedPdf
  
  public boundingBoxes: Rect[] = [];

  public canvasType: CanvasType = CanvasType.SingleSelection;
  public selectedBox: Rect = null;
  public backgroundImage: string;
  public isLoading: boolean = false;
  public areaIsSelected: boolean = false;
  public transliterationResult: string[] = null;

  public goToPage: number = 1;
  public uploadedImageBlob: File = null;

  public textId: number = null;
  public transliterationId: number = null;

  public isLoadedFromServer: boolean = false;
  public isTextFixed: boolean = false;

  public takeTextId: number;
  public takeTransId: number;

  public viewOnly: boolean = false;
  public highlightQuery: string = null;
 
  @ViewChild('canvas') canvas: FabricCanvasComponent;
  @ViewChild('lineEditor',  { static: false }) lineEditor: LineEditorComponent;
  public lines: Letter[];


  constructor(
    // public matDialogRef: MatDialogRef<PdfUploaderComponent>,
              public authService: AuthService,
              private curedService: CuredService,
              private notificationService: NotificationService,
              public dialog: MatDialog,
              private route: ActivatedRoute) { 
                    // set some stuff
    // this.stage = 5;
    // this.transliterationResult = ["hello therew world", "there are the test lines", "enjoy them while they least"];
    // this.lines = [new Letter("helhello therew worldloi"), new Letter("there are the test lines"),
    //               new Letter("enjoy them while they least")];
    // this.addIndexes(this.lines);
  }

  ngOnInit(): void {
    this.highlightQuery = this.route.snapshot.queryParamMap.get('query');
    const textId: string = this.route.snapshot.queryParamMap.get('textId');
    const transId: string = this.route.snapshot.queryParamMap.get('transId');
    const viewOnly: boolean = this.route.snapshot.queryParamMap.get('viewOnly') == "true";
    if(textId != null && transId != null) {
      this.stage =5;
      this.takeTextId = +textId;
      this.takeTransId = +transId;
      this.viewOnly = viewOnly;
      if(this.viewOnly) {
        this.canvasType = CanvasType.ViewAmendment;
      }
    }

  }


  ngAfterViewInit() {
    this.canvas.props.canvasHeight = 500;
    this.canvas.props.canvasWidth = 800;
    if(this.takeTextId != null && this.takeTransId != null) {
      this.textId = this.takeTextId;
      this.transliterationId = this.takeTransId;
      this.isLoadedFromServer = true;
      this.loadImageFromServer();
      this.loadTransliteration();
    }

  }

  submit(isFixed: boolean) {
    if(this.transliterationId == null) {
      this.curedService.saveImage(this.uploadedImageBlob, this.textId).subscribe(imageName => {
        this.notificationService.showSuccess(`uploaded image for text ${this.textId}, image name ${imageName}`);
        this.createSubmission(isFixed, imageName)
      })
    } else {
      this.createSubmission(isFixed, null);
    }
    
  }

  createSubmission(isFixed: boolean, imageName: string = null) {
    let lines = this.lines.map(line => line.letter);
    let dimensions = this.boundingBoxes.map(box => new Dimensions(box.left, box.top, box.getScaledHeight(), box.getScaledWidth()))
   
    this.curedService.createSubmission(this.textId, this.transliterationId, lines, dimensions, imageName, isFixed).subscribe(result => {
      this.notificationService.showInfo("Successfully submitted");
      this.transliterationId = result;
      this.isTextFixed = isFixed;
    })
  }

  openDialog() {
    const dialogRef = this.dialog.open(TextCreatorComponent);

    dialogRef.afterClosed().subscribe(textId => {
      console.log(`Dialog result: ${textId}`);
      this.textId = textId;
    });
  }

  findATransliteration() {
    this.stage = 5;
    const dialogRef = this.dialog.open(TextCreatorComponent);
    dialogRef.componentInstance.selectTransliteration = true;
    dialogRef.componentInstance.showCreateOnNoResult = false;
    dialogRef.afterClosed().subscribe(result => {
      if(result) {
        this.textId = result[0];
        this.transliterationId = result[1];
        this.isLoadedFromServer = true;
        this.loadImageFromServer();
        this.loadTransliteration();
      } else {
        this.stage = 0;
      }

    });
  }

  loadTransliteration() {
    this.curedService.loadTransliteration(this.textId, this.transliterationId).subscribe(data => {
      this.processTransliteration(data.lines, data.boxes);
      this.isTextFixed = data.is_fixed;
      if(this.highlightQuery) {
        this.setHighlightByQuery(this.highlightQuery);
      }
    });
  }

  loadImageFromServer() {
    let fileReader = new FileReader();
    fileReader.addEventListener("load", () => {
      let imageToShow: any = fileReader.result;
      this.setCanvasImage(imageToShow);
    }, false);

    this.curedService.getImage(this.textId, this.transliterationId).subscribe(data => {
      fileReader.readAsDataURL(data);   
    })  
  }

  userPasted(e) {
    const items = (e.clipboardData || e.originalEvent.clipboardData).items;
    let blob = null;
    for (const item of items) {
      if (item.type.indexOf('image') === 0) {
        blob = item.getAsFile();
        this.notificationService.showSuccess("Imaged loaded from paste!")
        this.loadImage(null, blob);
        return;
      }
    }
    this.notificationService.showError("That wasnt an image...");
  }

  loadImage(event=null, pasteImage=null) {
    const supportedTypes = ["image/png", "image/jpeg"]
    //  "image/tiff"]
    const file: File = event ? event.target.files[0] : pasteImage;
    if(!supportedTypes.includes(file.type)) {
      alert("Unsupported file extension. Please upload a .png, .jpg, .jpeg .tif or .tiff")
      return;
    }
    const fileSize = file.size / 1024 / 1024; // in MiB
    if(fileSize > 20) {
      alert("File is too big. Maximum supported is 5MB")
      return;
    }

    let fileReader = new FileReader();

    fileReader.addEventListener("load", () => {
      this.isLoading = false;
      let imageToShow: any = fileReader.result;
      this.setCanvasImage(imageToShow);
      this.stage = 2;
      this.uploadedImageBlob = file;
 
    }, false);

    this.stage = 1;
    fileReader.readAsDataURL(file); 
  }

  setCanvasImage(imageToShow) {
    this.backgroundImage = imageToShow;
    this.canvas.props.canvasImage = imageToShow;
    this.canvas.setCanvasImage();
    this.canvas.props.canvasHeight = 600;
    this.canvas.props.canvasWidth = 700;
    this.canvas.forceCanvasSize();
    this.canvas.forceZoomOut(0.8);
  }


  loadPDF(event) {
    const supportedTypes = ["application/pdf"]
    const file:File = event.target.files[0];
    if(!supportedTypes.includes(file.type)) {
      alert("Unsupported file extension. Please upload a .pdf")
    }

    this.pdfFile = file;
    let fileReader = new FileReader();

    fileReader.addEventListener("load", () => {
      var typedarray = new Uint8Array(fileReader.result as ArrayBufferLike);
      this.pdfSrc = typedarray;
      this.stage = 1;
    });

    fileReader.readAsArrayBuffer(file); 

  }

  getResult() {
    return new SelectedPdf(this.pdfFile, this.currentpage)
  }

  selectPage() {
    this.isLoading = true;
    let selectedPdf = this.getResult()
    let reader = new FileReader();

    reader.addEventListener("load", () => {
      this.isLoading = false;
      let imageToShow: any = reader.result;
      this.backgroundImage = imageToShow;
      this.canvas.props.canvasImage = imageToShow;
      this.canvas.setCanvasImage();
      this.canvas.props.canvasHeight = 600;
      this.canvas.props.canvasWidth = 700;
      this.canvas.forceCanvasSize();
      this.canvas.forceZoomOut();
      this.stage = 2;
 
    }, false);

    this.curedService.convertPdf(selectedPdf).subscribe(result => {
      if(result) {
        reader.readAsDataURL(result); 
      }
    });
  }

  modeChanged(val) {
    // if(val == CanvasMode.Adjust) {
    //   this.stage = 4;
    // }
  }

  cancel() {
    // this.matDialogRef.close();
  }
  
  afterLoadComplete(pdf: PDFDocumentProxy) {
    this.totalPages = pdf.numPages;
  }

  public previous() {
    if (this.currentpage > 0) {
      if (this.currentpage == 1) {
        this.currentpage = this.totalPages;
      } else {
        this.currentpage--;
      }
    }
  }
 
  public next() {
    if (this.totalPages > this.currentpage) {
      this.currentpage = this.currentpage + 1 ;
    } else {
      this.currentpage = 1;
    }
  }

  public goToAPage() {
    if (this.totalPages >= this.goToPage) {
      this.currentpage = this.goToPage;
    } else {
      this.notificationService.showError("Bad page number");
    }
  }

  boxDeleted(index) {
    if(this.boundingBoxes) {
      this.boundingBoxes = this.boundingBoxes.filter(item => item.data.index.row != index.row);
      this.sortBoxes();
      this.updateBoundingBoxesIndexes()
      // this.lineEditor.deleteLine(index.row, false);
    } else {
      this.selectedBox = null;
    }
  }

  lineDeleted(index) {
    // let boxToRemove = this.boundingBoxes.find(item => item.data.index.row == index);
    // this.canvas.getCanvas().remove(boxToRemove);
    // this.boundingBoxes = this.boundingBoxes.filter(item => item.data.index.row != index);
    // this.sortBoxes();
    // this.updateBoundingBoxesIndexes() 
  }

  sortBoxes() {
    this.boundingBoxes.sort((a: Rect, b: Rect) => a.top - b.top);
  }

  updateTransliterationIndexes() {
    this.lines.forEach((line, row) => {
      line.index = new Index(row, 0);
    });
  }

  restart() {
    if(!confirm("Are you sure you are done with this text?")) {
      return;
    }
    location.reload();
    return;

    this.stage = 0;
    this.textId = null;
    this.transliterationId = null;
    this.backgroundImage = null;
    this.isLoadedFromServer = false;
    this.isTextFixed = false;
    this.boundingBoxes = [];
    this.lines = [];
    this.lineEditor.hardReset();
    this.canvas.hardReset();
  }

  fetchBoundingBoxes(allDimensions: Dimensions[] = [], selecteAreaBox = null) {
    let boundingBoxes = [];

    let row = 0;
    for(let dimensions of allDimensions) {
      let x = dimensions.x
      let y = dimensions.y
      if(selecteAreaBox) {
        x += selecteAreaBox.left
        y += selecteAreaBox.top
      }

      let rect = this.canvas.makeRectangle(x, y, dimensions.width, dimensions.height,
        this.canvas.DEFAULT_RECT_FILL, 'blue', true, new Index(row, 0), true)

      boundingBoxes.push(rect);
      row++;
    }

    this.boundingBoxes = boundingBoxes;

    if(selecteAreaBox) {
      this.canvas.getCanvas().remove(selecteAreaBox);
    }
    
    this.canvas.addRectangles(boundingBoxes);
    this.updateBoundingBoxesIndexes();
  }

  areaSelected() {
    this.stage = 4;

    this.areaIsSelected = true;
    this.isLoading = true;
    let b = this.selectedBox;
    let x = ((this.canvas.getCanvas().backgroundImage as unknown) as FabricImage).toDataURL({
      left: b.left, top: b.top, height: b.getScaledHeight(), width: b.getScaledWidth()})
    this.curedService.getTransliterations(x).subscribe(data => {
      if(data.lines.length == 0) {
        this.notificationService.showWarning("AI failed to parse the image, there was probably error while loading the image, please try again from the start", 20000)
        this.stage = 3;
        return;
      } 
      
      this.processTransliteration(data.lines, data.dimensions);
      
    });
  }

  fetchTransliterations(lines: string[]) {
    this.transliterationResult = lines;
    this.lines = [];
    this.transliterationResult.forEach(line => {
      this.lines.push(new Letter(line));
    })
    this.lines = this.addIndexes(this.lines);
    this.lineEditor.setLines(this.lines);
  }

  processTransliteration(lines: string[], dimensions: Dimensions[], isBoxesFromServer: boolean = false) {
    this.fetchTransliterations(lines)

    if(isBoxesFromServer) {
      this.fetchBoundingBoxes(dimensions, null);
    } else {
      this.fetchBoundingBoxes(dimensions, this.selectedBox);
    }
  
    this.isLoading = false;
    this.stage = 5;
    this.canvas.allowedActions = [this.canvas.panMode, this.canvas.adjustMode, this.canvas.deleteMode, this.canvas.addMode];
    this.canvas.changeMode(CanvasMode.Pan);
  }

 

  updateBoundingBoxesIndexes() {
    this.boundingBoxes.forEach((box, row) => {
      box.data = new RectData(new Index(row, 0));
    });
  }

  goBack() {
    if(this.stage == 3 || this.stage == 2) {
      this.backgroundImage = null;
      this.selectedBox = null;
        this.canvas.hardReset();
        this.canvas.allowedActions = [this.canvas.panMode, this.canvas.addMode];
      if(this.pdfFile == null) {
        this.stage = 0;
      } else {
        this.stage = 1;
      }
    } else if(this.stage == 5) {
      this.stage = 3;
      this.canvas.removeAllRects()
      this.canvas.addRectangles([this.selectedBox])
      this.canvas.allowedActions = [this.canvas.panMode, this.canvas.adjustMode];
    } else if(this.stage == 1){
      this.pdfFile = null;
      this.stage = 0;
    }
  }


  boxAdded(newRect: Rect) {
    if(this.stage == 2) {
      let newIndex = new Index(0, 0);
      newRect.data = new RectData(newIndex);
      this.selectedBox = newRect;
      this.canvas.allowedActions = [this.canvas.panMode, this.canvas.adjustMode];
      this.stage = 3;
    } else if(this.stage == 5) {
      this.boundingBoxes.push(newRect);
      this.sortBoxes();
      this.updateBoundingBoxesIndexes();
    }
  }

  exportResult() {
    var lines = `Transliterations generated by CuReD (https://ben-digpasts.com/cured)\n\n`;
    this.lines.forEach(line => {
      lines += line.letter + "\n";
    })

    var transliteratinsBlob = new Blob([lines], {type: "text/plain;charset=utf-8"});
    saveAs(transliteratinsBlob, `CuReD-Result.txt`);
  }

  setHighlightByQuery(query: string) {
    let index = null;
    this.lines.forEach((line, lindeInex) => {
      if(line.letter.includes(query)) {
        index = new Index(lindeInex, 0);
        return;
      }
    })

    if(index == null) {
      return;
    }

    this.updateCanvasSelectedBox(index);
    this.updateTextViewerLetters(index);
  }

  transliterationLineHover(event: LetterHover) {
    if(event.active) {
      if(this.highlightQuery) { // first hover won't remove highlight
        this.highlightQuery = null;
        return;
      }
      this.updateCanvasSelectedBox(event.letterIndex);
      this.updateTextViewerLetters(event.letterIndex);
    }
 
  }

  boxSelectionChanged(index) {
    this.updateTextViewerLetters(index);
  }

  updateCanvasSelectedBox(letterIndex: Index) {
    if(letterIndex == null) {
      return;
    }
    
    let row = letterIndex.row;
    let selectedRect = undefined;
    if(this.boundingBoxes.length > row) {
      selectedRect = this.boundingBoxes[row];
    }

    this.canvas.changeSelection(selectedRect);
  }

  updateTextViewerLetters(index: Index) {
    if(this.lines == null || this.lines.length == 0 || this.lineEditor == null) {
      return;
    }

    this.lineEditor.setNewSelectedLine(index);
  }

  addIndexes(letters: Letter[]) {
    for (let row = 0; row < letters.length; row++) {
      letters[row].index = new Index(row, 0);
      
    }
    return letters;
  }

}

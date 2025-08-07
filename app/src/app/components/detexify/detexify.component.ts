import { AfterViewInit, Component, OnInit, ViewChild } from '@angular/core';
import { Letter, Prediction } from 'src/app/models/letter';
import { DetexifyService } from 'src/app/services/detexify.srevice';
import { CanvasType, FabricCanvasComponent } from '../fabric-canvas/fabric-canvas.component';

@Component({
  selector: 'app-detexify',
  templateUrl: './detexify.component.html',
  styleUrls: ['./detexify.component.scss']
})
export class DetexifyComponent implements AfterViewInit {
  @ViewChild('canvas') canvas: FabricCanvasComponent;

  constructor(private detexifyService: DetexifyService) { }

  public canvasType = CanvasType.Drawing;

  public predictions: Prediction[];

  public isLoading: boolean = false;
  
  ngAfterViewInit() {
    this.canvas.props.canvasHeight = 500;
    this.canvas.props.canvasWidth = 200;
    this.canvas.setCanvasSize();
  }

  modeChanged(val) {
  }

  getScore(probabiltiy: number) {
    return (probabiltiy * 100).toString().slice(0, 5) + "%";
  }

  getPrediction(isSecondTime=false) {
    setTimeout(() => {
      this.predictions = null;
      const image = this.exportImage();
      const objects = this.canvas.getCanvas().getObjects();
      if(objects.length == 0 && !isSecondTime) {
        this.getPrediction(true);
      } else {
        this.isLoading = true;
        this.detexifyService.postSingleImageGuess(image).subscribe(data => {
          if(data.length > 0) {
            this.predictions = data;
          }
          this.isLoading = false;
        });
      }
    } , 100);  
  }

  exportImage() {
    return this.canvas.getCanvas().toDataURL({format: "png"});
  }

}

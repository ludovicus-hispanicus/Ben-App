import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';

// Angular Material
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { TrainingComponent } from './training.component';
import { YoloTrainingModule } from '../yolo-training/yolo-training.module';
import { PdfUploaderModule } from '../cure-d/cured.module';
import { ProductionModule } from '../production/production.module';
import { BatchRecognitionModule } from '../batch-recognition/batch-recognition.module';

@NgModule({
  declarations: [
    TrainingComponent
  ],
  imports: [
    CommonModule,
    FormsModule,
    MatButtonModule,
    MatIconModule,
    MatFormFieldModule,
    MatInputModule,
    MatSelectModule,
    MatProgressSpinnerModule,
    MatProgressBarModule,
    MatTooltipModule,
    MatCheckboxModule,
    YoloTrainingModule,
    PdfUploaderModule,
    ProductionModule,
    BatchRecognitionModule
  ],
  exports: [
    TrainingComponent
  ]
})
export class TrainingModule { }

import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';

import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatMenuModule } from '@angular/material/menu';

import { TextEditorModule } from '../cure-d/text-editor/text-editor.module';
import { LineSegmentationComponent } from './line-segmentation.component';

@NgModule({
  imports: [
    CommonModule,
    FormsModule,
    MatButtonModule,
    MatIconModule,
    MatTooltipModule,
    MatProgressSpinnerModule,
    MatMenuModule,
    TextEditorModule,
  ],
  declarations: [
    LineSegmentationComponent,
  ],
  exports: [
    LineSegmentationComponent,
  ]
})
export class LineSegmentationModule {}

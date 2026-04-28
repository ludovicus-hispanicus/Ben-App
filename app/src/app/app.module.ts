import { NgModule } from '@angular/core';
import { BrowserModule } from '@angular/platform-browser';

import { AppRoutingModule } from './app-routing.module';
import { AppComponent } from './app.component';
import { BrowserAnimationsModule } from '@angular/platform-browser/animations';
import { MatSliderModule } from '@angular/material/slider';
import {MatIconModule} from '@angular/material/icon';
import {MatTooltipModule} from '@angular/material/tooltip';
import {MatButtonToggleModule} from '@angular/material/button-toggle';
import {MatButtonModule} from '@angular/material/button';
import {MatProgressSpinnerModule} from '@angular/material/progress-spinner';
import { HttpClientModule, HTTP_INTERCEPTORS } from '@angular/common/http';
import { authInterceptorProviders } from './auth/auth.interceptor';
import { JwtHelperService, JWT_OPTIONS  } from '@auth0/angular-jwt';
import { HomeModule } from './components/home/home.module';
import { ToastrModule } from 'ngx-toastr';
import { MatDialogModule } from '@angular/material/dialog';
import { PdfUploaderModule } from './components/cure-d/cured.module';
import { errorInterceptorProviders } from './interceptors/error.interceptor';
import { KeyboardShortcutsModule }     from 'ng-keyboard-shortcuts';
import { AdminPanelModule } from './components/admin-panel/admin-panel.module';
import { AboutModule } from './components/about/about.module';
import { YoloTrainingModule } from './components/yolo-training/yolo-training.module';
import { TrainingModule } from './components/training/training.module';
import { SettingsModule } from './components/settings/settings.module';
import { ProductionModule } from './components/production/production.module';
import { CureModule } from './components/cure/cure.module';
import { DocumentLibraryModule } from './components/document-library/document-library.module';
import { LineSegmentationModule } from './components/line-segmentation/line-segmentation.module';
import { SegmentationModule } from './components/segmentation/segmentation.module';
import { ConfirmDialogComponent } from './components/common/confirm-dialog/confirm-dialog.component';
import { LabelDialogComponent } from './components/common/label-dialog/label-dialog.component';
import { SaveDialogComponent } from './components/common/save-dialog/save-dialog.component';
import { ImageBrowserDialogComponent } from './components/common/image-browser-dialog/image-browser-dialog.component';
import { IdentifierDialogComponent } from './components/common/identifier-dialog/identifier-dialog.component';
import { FolderPickerDialogComponent } from './components/common/folder-picker-dialog/folder-picker-dialog.component';
import { FormsModule, ReactiveFormsModule } from '@angular/forms';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatAutocompleteModule } from '@angular/material/autocomplete';
import { MatSelectModule } from '@angular/material/select';
import { MatDividerModule } from '@angular/material/divider';


@NgModule({
  declarations: [
    AppComponent,
    ConfirmDialogComponent,
    LabelDialogComponent,
    SaveDialogComponent,
    ImageBrowserDialogComponent,
    IdentifierDialogComponent,
    FolderPickerDialogComponent,
 ],
  imports: [
    BrowserModule,
    HttpClientModule,
    AppRoutingModule,
    BrowserAnimationsModule,
    MatSliderModule,
    MatIconModule,
    MatTooltipModule,
    MatButtonToggleModule,
    MatButtonModule,
    MatProgressSpinnerModule,
    MatDialogModule,
    MatFormFieldModule,
    MatInputModule,
    MatAutocompleteModule,
    MatSelectModule,
    MatDividerModule,
    FormsModule,
    ReactiveFormsModule,
    ToastrModule.forRoot(),
    HomeModule,
    PdfUploaderModule,
    AdminPanelModule,
    AboutModule,
    YoloTrainingModule,
    TrainingModule,
    SettingsModule,
    ProductionModule,
    CureModule,
    DocumentLibraryModule,
    LineSegmentationModule,
    SegmentationModule,
    KeyboardShortcutsModule.forRoot()
  ],
  exports: [
  ],
  providers: [
    errorInterceptorProviders,
    authInterceptorProviders,
    { provide: JWT_OPTIONS, useValue: JWT_OPTIONS },
    JwtHelperService,

  ],
  bootstrap: [AppComponent]
})
export class AppModule { }

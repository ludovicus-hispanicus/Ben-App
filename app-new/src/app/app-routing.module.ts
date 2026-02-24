import { NgModule } from '@angular/core';
import { RouterModule, Routes } from '@angular/router';
import { AdminPanelComponent } from './components/admin-panel/admin-panel.component';
import { AboutComponent } from './components/about/about.component';
import { YoloTrainingComponent } from './components/yolo-training/yolo-training.component';
import { TrainingComponent } from './components/training/training.component';
import { SettingsComponent } from './components/settings/settings.component';
import { CureComponent } from './components/cure/cure.component';
import { DocumentLibraryComponent } from './components/document-library/document-library.component';


const routes: Routes = [
  {
    path: '',
    component: AdminPanelComponent  // Dashboard as landing page
  },
  // CuReD - unified OCR curation, training, models & export
  {
    path: 'cured',
    component: TrainingComponent
  },
  {
    path: 'dashboard',
    component: AdminPanelComponent
  },
  {
    path: 'about',
    component: AboutComponent
  },
  {
    path: 'yolo-training',
    component: YoloTrainingComponent
  },
  {
    path: 'settings',
    component: SettingsComponent
  },
  // CuRe Sign Classifier
  {
    path: 'cure',
    component: CureComponent
  },
  {
    path: 'cure/editor',
    component: CureComponent
  },
  // Document Library - unified image browser
  {
    path: 'library',
    component: DocumentLibraryComponent
  }
];

@NgModule({
  imports: [RouterModule.forRoot(routes)],
  exports: [RouterModule]
})
export class AppRoutingModule { }

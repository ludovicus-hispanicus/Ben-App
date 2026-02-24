import { NgModule } from '@angular/core';
import { RouterModule, Routes } from '@angular/router';
import { AmendmentComponent } from './components/amendment/amendment.component';
import { DetexifyComponent } from './components/detexify/detexify.component';
import { CuredComponent } from './components/cure-d/cured.component';
import { AdminPanelComponent } from './components/admin-panel/admin-panel.component';
import { AboutComponent } from './components/about/about.component';
import { DictionaryOcrComponent } from './components/dictionary-ocr/dictionary-ocr.component';
import { YoloTrainingComponent } from './components/yolo-training/yolo-training.component';


const routes: Routes = [
  {
    path: '',
    component: AdminPanelComponent  // Dashboard as landing page
  },
  {
    path: 'amendment',
    component: AmendmentComponent,
  },
  {
    path: 'decuneify',
    component: DetexifyComponent
  },
  {
    path: 'cured',
    component: CuredComponent
  },
  {
    path: 'cured/select-page',
    component: CuredComponent
  },
  {
    path: 'cured/editor',
    component: CuredComponent
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
    path: 'dictionary-ocr',
    component: DictionaryOcrComponent
  },
  {
    path: 'yolo-training',
    component: YoloTrainingComponent
  }
];

@NgModule({
  imports: [RouterModule.forRoot(routes)],
  exports: [RouterModule]
})
export class AppRoutingModule { }

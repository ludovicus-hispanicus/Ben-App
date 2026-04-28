import { NgModule, Injectable } from '@angular/core';
import { RouterModule, Routes, CanActivate, Router } from '@angular/router';
import { AdminPanelComponent } from './components/admin-panel/admin-panel.component';
import { AboutComponent } from './components/about/about.component';
import { YoloTrainingComponent } from './components/yolo-training/yolo-training.component';
import { TrainingComponent } from './components/training/training.component';
import { SettingsComponent } from './components/settings/settings.component';
import { CureComponent } from './components/cure/cure.component';
import { DocumentLibraryComponent } from './components/document-library/document-library.component';
import { LineSegmentationComponent } from './components/line-segmentation/line-segmentation.component';
import { SegmentationComponent } from './components/segmentation/segmentation.component';
import { ModuleService } from './services/module.service';

@Injectable({ providedIn: 'root' })
export class ModuleGuard implements CanActivate {
  constructor(private moduleService: ModuleService, private router: Router) {}

  canActivate(route: any): boolean {
    const moduleId = route.data?.moduleId;
    if (moduleId && !this.moduleService.isEnabled(moduleId)) {
      this.router.navigate(['/']);
      return false;
    }
    return true;
  }
}

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
    component: YoloTrainingComponent,
    canActivate: [ModuleGuard],
    data: { moduleId: 'yolo' }
  },
  {
    path: 'settings',
    component: SettingsComponent
  },
  // CuRe Sign Classifier
  {
    path: 'cure',
    component: CureComponent,
    canActivate: [ModuleGuard],
    data: { moduleId: 'cure' }
  },
  {
    path: 'cure/editor',
    component: CureComponent,
    canActivate: [ModuleGuard],
    data: { moduleId: 'cure' }
  },
  // Document Library - unified image browser
  {
    path: 'library',
    component: DocumentLibraryComponent,
    canActivate: [ModuleGuard],
    data: { moduleId: 'library' }
  },
  // Line Segmentation - annotation tool for text line ground truth
  {
    path: 'line-segmentation',
    component: LineSegmentationComponent,
    canActivate: [ModuleGuard],
    data: { moduleId: 'line_segmentation' }
  },
  // Segmentation - dashboard, batch destitch, training, models
  {
    path: 'segmentation',
    component: SegmentationComponent,
    canActivate: [ModuleGuard],
    data: { moduleId: 'line_segmentation' }
  },
];

@NgModule({
  imports: [RouterModule.forRoot(routes)],
  exports: [RouterModule]
})
export class AppRoutingModule { }

import { NgModule } from '@angular/core';
import { RouterModule, Routes } from '@angular/router';
import { AmendmentComponent } from './components/amendment/amendment.component';
import { DetexifyComponent } from './components/detexify/detexify.component';
import { HomeComponent } from './components/home/home.component';
import { AuthGuardService as AuthGuard } from './auth/auth-guard.service';
import { DemoComponent } from './components/demo/demo.component';
import { CuredComponent } from './components/cure-d/cured.component';
import { AdminPanelComponent } from './components/admin-panel/admin-panel.component';
import { GalleryComponent } from './components/gallery/gallery.component';
import { AboutComponent } from './components/about/about.component';


const routes: Routes = [
  {
    path: '',
    component: HomeComponent
  },
  {
    path: 'home',
    component: HomeComponent
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
    path: 'demo',
    component: DemoComponent
  },
  {
    path: 'cured',
    component: CuredComponent
  },
  {
    path: 'adminpanel',
    component: AdminPanelComponent
  },
  {
    path: 'gallery',
    component: GalleryComponent
  },
  {
    path: 'about',
    component: AboutComponent
  }
];

@NgModule({
  imports: [RouterModule.forRoot(routes)],
  exports: [RouterModule]
})
export class AppRoutingModule { }

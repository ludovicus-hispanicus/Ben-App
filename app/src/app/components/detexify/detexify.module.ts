import { NgModule } from "@angular/core";
import { BrowserModule } from "@angular/platform-browser";
import { FabricCanvasModule } from "../fabric-canvas/fabric-canvas.module";
import { DetexifyComponent } from "./detexify.component";
import { MatButtonModule } from "@angular/material/button";
import {MatProgressSpinnerModule} from '@angular/material/progress-spinner';


@NgModule({
    imports: [
        BrowserModule,
        FabricCanvasModule,
        MatButtonModule,
        MatProgressSpinnerModule
    ],
    declarations: [DetexifyComponent],
    exports: [DetexifyComponent],
    providers: [],
 })
 
 export class DetexifyModule {
 }
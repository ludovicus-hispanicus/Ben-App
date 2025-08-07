import { CommonModule } from "@angular/common";
import { NgModule } from "@angular/core";
import { MatButtonModule } from "@angular/material/button";
import { MatButtonToggleModule } from "@angular/material/button-toggle";
import { MatIconModule } from "@angular/material/icon";
import { MatSliderModule } from "@angular/material/slider";
import { MatTooltipModule } from "@angular/material/tooltip";
import { KeyboardShortcutsModule } from "ng-keyboard-shortcuts";
import { FabricCanvasComponent } from "./fabric-canvas.component";


@NgModule({
    imports: [    
        MatIconModule,
        MatTooltipModule,
        MatButtonToggleModule,
        MatButtonModule,
        MatSliderModule,
        CommonModule,
        KeyboardShortcutsModule
    ],
    declarations: [FabricCanvasComponent],
    exports: [FabricCanvasComponent],
    providers: [],
 })
 
 export class FabricCanvasModule {
 }